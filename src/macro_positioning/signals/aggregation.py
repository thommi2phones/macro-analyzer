"""Per-ticker signal aggregation for the scoring composer.

Reads active Signal rows for a ticker and produces a multi-window
directional-bias summary the scorer folds in:

  * 7 windows — 1d / 3d / 7d / 14d / 28d / 90d / 180d — each with its
    own recency half-life. Every window is a full aggregate (net bias,
    direction, confidence, alignment_score, provenance).
  * A weighted **blend** across windows. Baseline weights are middle-
    heavy (14d/28d peak) to match a "few days to few months, exit every
    few weeks" hold horizon. These are a hand-tuned prior; the follow-up
    commit swaps them for per-regime seeds × trailing per-window edge so
    the weights *learn* from what has been predicting PnL.
  * Cross-window **trend** analysis — is the short bloc flipping vs the
    long bloc? Powers the "recent flip vs long thesis" divergence read
    that a single 90d aggregate used to hide.
  * A **timeframe multiplier** applied inside every window: intraday
    reads (2H/4H) count 0.3×, swing 1.0×, position 1.4×, strategic 1.6×.
    A 2H tactical flip does not carry equal weight to a daily/weekly
    thesis change.

Top-level fields (`n_signals`, `net_bias`, `bias_direction`, …) mirror
the blend so existing callers keep working. New `windows` / `blend` /
`cross_window` keys carry the richer view.

Recency-decayed within each window: a signal extracted at the
window's half-life ago is worth 0.5× a fresh one. Half-life is roughly
half the window (14d window → 7d half-life) so recency dominates
without silently zeroing the older half of the window.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

from macro_positioning.core.settings import settings
from macro_positioning.manual.authors import seeded_author_ids


# Sides that imply "buy this" vs "sell this" vs "get out" buckets.
_LONG_SIDES = {"LONG", "ADD"}
_SHORT_SIDES = {"SHORT", "HEDGE"}
_EXIT_SIDES = {"EXIT", "TRIM"}
_WATCH_SIDES = {"WATCH"}
_AVOID_SIDES = {"AVOID"}


# ── Window matrix + baseline blend ─────────────────────────────────────────
#
# (label, since_days, half_life_days). Half-life ≈ ½ the window so recency
# dominates without silently zeroing older signals inside the window.
DEFAULT_WINDOWS: list[tuple[str, int, float]] = [
    ("1d",   1,    0.5),
    ("3d",   3,    1.5),
    ("7d",   7,    3.0),
    ("14d",  14,   7.0),
    ("28d",  28,   14.0),
    ("90d",  90,   30.0),
    ("180d", 180,  60.0),
]

# Baseline (cold-start) blend weights. Middle-heavy — 14d/28d peak at 22%
# each because the operator's typical horizon is a few days to a few
# months with a re-eval every few weeks. Thesis flanks (90d/180d = 26%)
# anchor conviction; tactical flanks (1d/3d = 14%) surface fresh flips
# without letting them dominate the score.
#
# Next commit: these become per-regime seeds and get multiplied by each
# window's trailing prediction edge, so the effective weights adapt to
# which windows are actually predicting PnL in the current tape.
DEFAULT_BLEND_WEIGHTS: dict[str, float] = {
    "1d":   0.04,
    "3d":   0.10,
    "7d":   0.16,
    "14d":  0.22,
    "28d":  0.22,
    "90d":  0.16,
    "180d": 0.10,
}


# ── Timeframe multiplier ───────────────────────────────────────────────────
#
# Applied inside _signal_weight so every window inherits it.
_HORIZON_MULT: dict[str, float] = {
    "intraday":  0.3,
    "swing":     1.0,
    "position":  1.4,
    "strategic": 1.6,
}

# Fallback parser: instrument_detail_json.chart_timeframe when horizon
# is null. "2H", "4H", "15M", "intraday" → tactical (0.3). Monthly gets
# strategic-tier weight; weekly gets position-tier; daily is the swing
# baseline. Word-boundaries keep "monthly" from matching inside longer
# tokens.
_TF_INTRADAY_RX = re.compile(r"\d+\s*-?\s*(?:h|hr|hour|m|min|minute)\b", re.I)
_TF_KEYWORDS: list[tuple[str, float]] = [
    ("monthly", 1.6),
    ("weekly",  1.4),
    ("daily",   1.0),
    ("intraday", 0.3),
]


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _recency_weight(age_days: float, *, half_life_days: float) -> float:
    """0..1 multiplier. e^(-ln(2) * age / half_life)."""
    if age_days <= 0:
        return 1.0
    if half_life_days <= 0:
        return 0.0
    return math.exp(-math.log(2) * age_days / half_life_days)


def _timeframe_multiplier(row: dict) -> float:
    """Return a per-row weight multiplier reflecting the *timeframe of the
    call*, not its recency.

    Precedence:
      1. `horizon` enum from the extractor (intraday|swing|position|strategic)
      2. Regex over `instrument_detail_json.chart_timeframe` (from vision)
      3. 1.0 default (swing) — a signal we can't classify is treated as a
         normal swing-timeframe read, not silently discounted.
    """
    horizon = (row.get("horizon") or "").lower()
    if horizon in _HORIZON_MULT:
        return _HORIZON_MULT[horizon]

    raw = row.get("instrument_detail_json")
    if raw:
        try:
            inst = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            inst = {}
        tf = (inst.get("chart_timeframe") or "").lower() if isinstance(inst, dict) else ""
        if tf:
            # Numeric intraday timeframes ("2h", "15m") win first — a
            # keyword like "daily-view of intraday chart" is ambiguous;
            # explicit numbers aren't.
            if _TF_INTRADAY_RX.search(tf):
                return 0.3
            for kw, mult in _TF_KEYWORDS:
                if kw in tf:
                    return mult
    return 1.0


def _signal_weight(row: dict, *, now: datetime, half_life_days: float) -> float:
    """Effective weight = weighted_score × timeframe_multiplier × recency.

    `weighted_score` was snapshotted at extract time as
    conviction × source_trust × author_trust. We multiply timeframe +
    recency here so the aggregator can be invoked with different windows
    and horizons without re-running extraction.
    """
    base = row.get("weighted_score")
    if base is None:
        base = (row.get("conviction") or 1.0) * (
            row.get("source_trust_weight") or 1.0
        ) * (row.get("author_trust_weight") or 1.0)
    tf_mult = _timeframe_multiplier(row)
    extracted = _parse_dt(row.get("extracted_at"))
    if extracted is None:
        return float(base) * tf_mult
    age = (now - extracted).total_seconds() / 86400.0
    return float(base) * tf_mult * _recency_weight(age, half_life_days=half_life_days)


def _alignment_score(net_bias: float, *, scale: float = 12.0) -> int:
    """Map net_bias (long_weight - short_weight) into 0..10.

    Negative net_bias (more short than long) clamps to 0 — this score
    measures *positive* directional conviction, not absolute magnitude.
    Use `bias_direction` for shorts.
    """
    if net_bias <= 0:
        return 0
    return max(0, min(10, round((net_bias / scale) * 10)))


# ── Per-window reduction ──────────────────────────────────────────────────


def _empty_window_agg() -> dict:
    return {
        "n_signals": 0,
        "long_weight": 0.0, "short_weight": 0.0, "exit_weight": 0.0,
        "watch_count": 0, "avoid_count": 0,
        "net_bias": 0.0, "bias_direction": "neutral", "bias_confidence": 0.0,
        "alignment_score": 0,
        "dominant_horizon": None, "dominant_catalyst": None,
    }


def _reduce_window(
    rows: list[dict], *, now: datetime, half_life_days: float,
) -> dict:
    """Collapse a list of already-window-filtered signal rows into a
    single-window aggregate dict. Pure — no I/O, no ranking (top_signals
    are computed once at the top level from the union of all rows)."""
    if not rows:
        return _empty_window_agg()

    long_w = short_w = exit_w = 0.0
    watch_n = avoid_n = 0
    horizon_counts: dict[str, int] = {}
    catalyst_counts: dict[str, int] = {}

    for row in rows:
        w = _signal_weight(row, now=now, half_life_days=half_life_days)
        side = (row.get("side") or "").upper()
        if side in _LONG_SIDES:
            long_w += w
        elif side in _SHORT_SIDES:
            short_w += w
        elif side in _EXIT_SIDES:
            exit_w += w
        elif side in _WATCH_SIDES:
            watch_n += 1
        elif side in _AVOID_SIDES:
            avoid_n += 1

        h = row.get("horizon")
        if h:
            horizon_counts[h] = horizon_counts.get(h, 0) + 1
        c = row.get("catalyst_type")
        if c:
            catalyst_counts[c] = catalyst_counts.get(c, 0) + 1

    net = long_w - short_w
    total_directional = long_w + short_w
    if total_directional <= 0:
        bias_direction = "exit_bias" if exit_w > 0 else (
            "watch_only" if (watch_n or avoid_n) else "neutral"
        )
        bias_confidence = 0.0
    elif long_w >= short_w:
        bias_direction = "long"
        bias_confidence = round(long_w / total_directional, 4)
    else:
        bias_direction = "short"
        bias_confidence = round(short_w / total_directional, 4)

    return {
        "n_signals": len(rows),
        "long_weight": round(long_w, 4),
        "short_weight": round(short_w, 4),
        "exit_weight": round(exit_w, 4),
        "watch_count": watch_n,
        "avoid_count": avoid_n,
        "net_bias": round(net, 4),
        "bias_direction": bias_direction,
        "bias_confidence": bias_confidence,
        "alignment_score": _alignment_score(net),
        "dominant_horizon": max(horizon_counts, key=horizon_counts.get) if horizon_counts else None,
        "dominant_catalyst": max(catalyst_counts, key=catalyst_counts.get) if catalyst_counts else None,
    }


# ── Blend + cross-window analysis ─────────────────────────────────────────


def _blend_windows(
    per_window: dict[str, dict], weights: dict[str, float],
) -> dict:
    """Weighted blend of the per-window aggregates → the "one number" the
    composer reads. Direction is re-derived from the blended long/short
    weights so a mix that nets short *is* a short blend, not a long one
    weighted by the wrong prior."""
    # Skip zero-weight windows so a caller can silence a window by
    # setting its weight to 0 without polluting the average.
    active = {k: w for k, w in weights.items() if w > 0 and k in per_window}
    if not active:
        return {**_empty_window_agg(), "weights_applied": {}, "coverage": 0.0}

    total_w = sum(active.values())
    long_w = sum(per_window[k]["long_weight"] * w for k, w in active.items()) / total_w
    short_w = sum(per_window[k]["short_weight"] * w for k, w in active.items()) / total_w
    exit_w = sum(per_window[k]["exit_weight"] * w for k, w in active.items()) / total_w
    # Coverage — share of the weight mass whose window actually saw at
    # least one signal. Low coverage warns the caller the blend leans on
    # very few windows.
    coverage = sum(w for k, w in active.items() if per_window[k]["n_signals"] > 0) / total_w

    net = long_w - short_w
    total_directional = long_w + short_w
    if total_directional <= 0:
        bias_direction = "neutral"
        bias_confidence = 0.0
    elif long_w >= short_w:
        bias_direction = "long"
        bias_confidence = round(long_w / total_directional, 4)
    else:
        bias_direction = "short"
        bias_confidence = round(short_w / total_directional, 4)

    return {
        "long_weight": round(long_w, 4),
        "short_weight": round(short_w, 4),
        "exit_weight": round(exit_w, 4),
        "net_bias": round(net, 4),
        "bias_direction": bias_direction,
        "bias_confidence": bias_confidence,
        "alignment_score": _alignment_score(net),
        "weights_applied": {k: round(w / total_w, 4) for k, w in active.items()},
        "coverage": round(coverage, 4),
    }


# Short bloc = "recent tape"; long bloc = "thesis". Cross-window analysis
# compares them so the UI can flag a flip that hasn't yet swayed the blend
# (or already has).
_SHORT_BLOC = ("1d", "3d", "7d")
_LONG_BLOC = ("28d", "90d", "180d")


def _bloc_direction(
    per_window: dict[str, dict], labels: tuple[str, ...],
) -> tuple[str, float]:
    """Aggregate direction across a set of windows using summed weights.
    Returns (direction, confidence)."""
    long_w = sum(per_window.get(k, {}).get("long_weight", 0.0) for k in labels)
    short_w = sum(per_window.get(k, {}).get("short_weight", 0.0) for k in labels)
    total = long_w + short_w
    if total <= 0:
        return "neutral", 0.0
    if long_w >= short_w:
        return "long", round(long_w / total, 4)
    return "short", round(short_w / total, 4)


def _cross_window(per_window: dict[str, dict]) -> dict:
    """Compare the short (tactical) bloc against the long (thesis) bloc
    and label the trend. Downstream UI reads `trend` to badge divergence
    and `recent_flip` to warn on active sizing decisions."""
    short_dir, short_conf = _bloc_direction(per_window, _SHORT_BLOC)
    long_dir, long_conf = _bloc_direction(per_window, _LONG_BLOC)

    # "flipping_X" — both blocs have real signal, they disagree, and the
    # short bloc is meaningfully convinced. Confidence floor keeps a
    # 51/49 split from tripping a divergence badge.
    _CONF_FLOOR = 0.6
    if (short_dir != "neutral" and long_dir != "neutral"
            and short_dir != long_dir and short_conf >= _CONF_FLOOR):
        trend = f"flipping_{short_dir}"
        recent_flip = True
    elif short_dir == long_dir and short_dir != "neutral":
        trend = f"stable_{short_dir}"
        recent_flip = False
    else:
        trend = "mixed"
        recent_flip = False

    # Per-window agreement with the blend direction (blend not known
    # here — we compare each window to the LONG bloc's direction, which
    # is the thesis anchor). Aligned = same direction; diverging = opposite.
    aligned, diverging = [], []
    for label, agg in per_window.items():
        wd = agg["bias_direction"]
        if long_dir == "neutral" or wd == "neutral":
            continue
        if wd == long_dir:
            aligned.append(label)
        elif wd in ("long", "short"):
            diverging.append(label)

    return {
        "trend": trend,
        "recent_flip": recent_flip,
        "short_bloc": {"direction": short_dir, "confidence": short_conf},
        "long_bloc": {"direction": long_dir, "confidence": long_conf},
        "aligned_windows": aligned,
        "diverging_windows": diverging,
    }


# ── Public API ────────────────────────────────────────────────────────────


def aggregate_for_ticker(
    ticker: str,
    *,
    windows: Optional[list[tuple[str, int, float]]] = None,
    blend_weights: Optional[dict[str, float]] = None,
    top_n: int = 5,
    now: Optional[datetime] = None,
    db_path: Optional[Path] = None,
    # Legacy single-window API. If either is passed, the aggregator
    # collapses to a single custom window using those params — the pre-
    # multi-window behavior, for callers that still want it.
    since_days: Optional[int] = None,
    half_life_days: Optional[float] = None,
) -> dict:
    """Aggregate active signals for `ticker` across a matrix of windows.

    Returns a dict with:
      * top-level fields matching the legacy single-window shape
        (`n_signals`, `net_bias`, `bias_direction`, `bias_confidence`,
        `alignment_score`, `long_weight`, `short_weight`, `exit_weight`,
        `watch_count`, `avoid_count`, `dominant_horizon`,
        `dominant_catalyst`, `top_signals`, `contributing_authors`,
        `contributing_sources`) — directional fields come from the blend,
        counts come from the union of all windows;
      * `windows`: {label: per-window aggregate} for all configured windows;
      * `blend`: weighted blend across windows (the "one number" for the
        composer);
      * `cross_window`: short-bloc vs long-bloc trend + divergence flags;
      * `blend_weights`: the weights used (baseline or caller-supplied).
    """
    if since_days is not None or half_life_days is not None:
        # Legacy single-window path.
        s = since_days if since_days is not None else 90
        h = half_life_days if half_life_days is not None else 14.0
        windows = [("legacy", s, h)]
        blend_weights = {"legacy": 1.0}

    windows = windows or DEFAULT_WINDOWS
    blend_weights = blend_weights or DEFAULT_BLEND_WEIGHTS

    db_path = db_path or settings.sqlite_path
    now = now or datetime.now(UTC)
    max_days = max(w[1] for w in windows)
    max_half_life = max(w[2] for w in windows)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        allowed = seeded_author_ids(conn)
        rows = [dict(r) for r in conn.execute(
            """
            SELECT signal_id, side, conviction, weighted_score,
                   source_slug, source_channel, author_id,
                   source_trust_weight, author_trust_weight,
                   horizon, catalyst_type, thesis_summary,
                   instrument_detail_json,
                   extractor_name, extracted_at
            FROM signals
            WHERE asset_ticker = ?
              AND status = 'active'
              AND extracted_at >= datetime('now', '-' || ? || ' days')
            ORDER BY extracted_at DESC
            """,
            (ticker.upper(), max_days),
        ).fetchall()]

    # Author allowlist — only explicitly-seeded voices count toward
    # conviction (see project_conviction_author_allowlist memory).
    rows = [r for r in rows if (r.get("author_id") or "") in allowed]

    # Union-of-windows provenance (from the widest window == every row)
    author_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    for r in rows:
        a = r.get("author_id")
        if a:
            author_counts[a] = author_counts.get(a, 0) + 1
        src = r.get("source_slug")
        if src:
            source_counts[src] = source_counts.get(src, 0) + 1

    # Per-window filter + reduce.
    per_window: dict[str, dict] = {}
    for label, since_d, hl in windows:
        cutoff = now - timedelta(days=since_d)
        window_rows = [
            r for r in rows
            if (_parse_dt(r.get("extracted_at")) or now) >= cutoff
        ]
        per_window[label] = _reduce_window(window_rows, now=now, half_life_days=hl)

    blend = _blend_windows(per_window, blend_weights)
    cross = _cross_window(per_window)

    # top_signals — ranked by weight over the widest window (all rows),
    # using its half-life so a fresh call outranks an older equal-base one.
    ranked = [
        (_signal_weight(r, now=now, half_life_days=max_half_life), r) for r in rows
    ]
    ranked.sort(key=lambda t: t[0], reverse=True)
    top_signals = [
        {
            "signal_id": r["signal_id"],
            "side": r["side"],
            "conviction": r["conviction"],
            "weighted_effective": round(w, 4),
            "author_id": r.get("author_id"),
            "source_slug": r.get("source_slug"),
            "extracted_at": r.get("extracted_at"),
            "horizon": r.get("horizon"),
            "catalyst_type": r.get("catalyst_type"),
            "thesis_summary": r.get("thesis_summary"),
            "timeframe_multiplier": round(_timeframe_multiplier(r), 4),
        }
        for w, r in ranked[:top_n]
    ]

    # Union-of-windows counts & dominance (matches pre-multi-window
    # top-level shape — a caller asking "how many signals do we have"
    # gets the full picture, not just the blend's directional mass).
    horizon_counts: dict[str, int] = {}
    catalyst_counts: dict[str, int] = {}
    watch_n_total = avoid_n_total = 0
    for r in rows:
        h = r.get("horizon")
        if h:
            horizon_counts[h] = horizon_counts.get(h, 0) + 1
        c = r.get("catalyst_type")
        if c:
            catalyst_counts[c] = catalyst_counts.get(c, 0) + 1
        side = (r.get("side") or "").upper()
        if side in _WATCH_SIDES:
            watch_n_total += 1
        elif side in _AVOID_SIDES:
            avoid_n_total += 1

    # Top-level bias_direction promotes watch/exit when the blend is
    # neutral — the blend only sees directional weights, but a wall of
    # WATCH or EXIT reads is itself the aggregate's message.
    top_direction = blend["bias_direction"]
    if top_direction == "neutral":
        if blend["exit_weight"] > 0:
            top_direction = "exit_bias"
        elif watch_n_total or avoid_n_total:
            top_direction = "watch_only"

    return {
        "ticker": ticker.upper(),
        # Rich multi-window view (new).
        "windows": per_window,
        "blend": blend,
        "cross_window": cross,
        "blend_weights": dict(blend_weights),
        # Back-compat top-level fields. Directional metrics from blend;
        # counts from the union of windows.
        "n_signals": len(rows),
        "long_weight": blend["long_weight"],
        "short_weight": blend["short_weight"],
        "exit_weight": blend["exit_weight"],
        "watch_count": watch_n_total,
        "avoid_count": avoid_n_total,
        "net_bias": blend["net_bias"],
        "bias_direction": top_direction,
        "bias_confidence": blend["bias_confidence"],
        "alignment_score": blend["alignment_score"],
        "dominant_horizon": max(horizon_counts, key=horizon_counts.get) if horizon_counts else None,
        "dominant_catalyst": max(catalyst_counts, key=catalyst_counts.get) if catalyst_counts else None,
        "top_signals": top_signals,
        "contributing_authors": author_counts,
        "contributing_sources": source_counts,
    }


def aggregate_for_tickers(
    tickers: Iterable[str],
    *,
    windows: Optional[list[tuple[str, int, float]]] = None,
    blend_weights: Optional[dict[str, float]] = None,
    db_path: Optional[Path] = None,
    # Legacy args — passed through for callers still on the single-window
    # API. New callers should pass `windows` / `blend_weights` instead.
    since_days: Optional[int] = None,
    half_life_days: Optional[float] = None,
) -> dict[str, dict]:
    """Batch convenience — one aggregate per ticker. Single connection."""
    out: dict[str, dict] = {}
    now = datetime.now(UTC)
    for t in tickers:
        out[t.upper()] = aggregate_for_ticker(
            t,
            windows=windows,
            blend_weights=blend_weights,
            now=now,
            db_path=db_path,
            since_days=since_days,
            half_life_days=half_life_days,
        )
    return out


# Sensible defaults for the per-pass net_bias scale (see directional_scale).
_SCALE_FLOOR = 3.0        # sparse passes can't over-amplify noise
_SCALE_DEFAULT = 4.0      # used when no ticker in the pass carries a signal


def directional_scale(
    aggregates: dict[str, dict],
    *,
    percentile: float = 0.9,
    floor: float = _SCALE_FLOOR,
    default: float = _SCALE_DEFAULT,
) -> float:
    """The net_bias magnitude that should read as *full* directional
    conviction for this scoring pass — used by the signal_alignment
    scorer to normalise net_bias into 0..1.

    Reads the top-level `net_bias` (which reflects the blend for
    multi-window aggregates), so pass-scale calibration continues to
    work identically for old and new callers.

    Dynamic by design: the most-convicted tickers *this pass* define the
    top of the scale, so the component auto-calibrates as signal volume
    and conviction grow instead of relying on a hand-tuned constant.
    """
    mags = sorted(
        abs(a.get("net_bias") or 0.0)
        for a in aggregates.values()
        if (a.get("n_signals") or 0) > 0 and (a.get("net_bias") or 0.0) != 0.0
    )
    if not mags:
        return default
    idx = min(len(mags) - 1, int(round(percentile * (len(mags) - 1))))
    return max(floor, mags[idx])

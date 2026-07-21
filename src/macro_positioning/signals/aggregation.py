"""Per-ticker signal aggregation for the scoring composer.

Reads active Signal rows for a ticker and produces a directional-bias
summary the scorer can fold in: net long-vs-short weight, dominant
catalyst type, top contributing authors, and a 0..10 `alignment_score`
that summarises overall conviction.

Recency-decayed: a signal extracted 14 days ago carries half the weight
of a signal extracted today. Half-life is configurable so the same code
can power "what does the past week say?" (half_life=3) and "what does
the past quarter say?" (half_life=30) views.
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import UTC, datetime
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


def _signal_weight(row: dict, *, now: datetime, half_life_days: float) -> float:
    """Effective weight = stored weighted_score × recency decay.

    `weighted_score` was snapshotted at extract time as
    conviction × source_trust × author_trust. We multiply by recency here
    so the aggregator can be invoked with different windows without
    re-running extraction.
    """
    base = row.get("weighted_score")
    if base is None:
        # Fall back to recomputing from raw components if older rows
        # predate the snapshot.
        base = (row.get("conviction") or 1.0) * (
            row.get("source_trust_weight") or 1.0
        ) * (row.get("author_trust_weight") or 1.0)
    extracted = _parse_dt(row.get("extracted_at"))
    if extracted is None:
        return float(base)
    age = (now - extracted).total_seconds() / 86400.0
    return float(base) * _recency_weight(age, half_life_days=half_life_days)


def _alignment_score(net_bias: float, *, scale: float = 12.0) -> int:
    """Map net_bias (long_weight - short_weight) into 0..10.

    `scale` is the bias level that maps to score=10 (chosen heuristically:
    two strong gov-insider buys = conviction 3 × source 1.2 × author 1.2
    × recency 1 ≈ 4.3 each → net ≈ 8.6, so a single strong buy lands ~5
    and two land ~7.

    Negative net_bias (more short than long) clamps to 0 — this score
    measures *positive* directional conviction, not absolute magnitude.
    Use `bias_direction` from the aggregate dict for shorts.
    """
    if net_bias <= 0:
        return 0
    return max(0, min(10, round((net_bias / scale) * 10)))


def aggregate_for_ticker(
    ticker: str,
    *,
    since_days: int = 90,
    half_life_days: float = 14.0,
    top_n: int = 5,
    now: Optional[datetime] = None,
    db_path: Optional[Path] = None,
) -> dict:
    """Aggregate active signals for `ticker` into a bias dict.

    Returns:
      {
        n_signals, long_weight, short_weight, exit_weight,
        watch_count, avoid_count,
        net_bias,                    # long_weight - short_weight
        bias_direction,              # long | short | neutral | exit_bias | watch_only
        bias_confidence,             # 0..1 — share of conviction on the winning side
        alignment_score,             # 0..10 — positive directional conviction
        dominant_horizon,            # most-common horizon among top signals
        dominant_catalyst,           # most-common catalyst_type
        top_signals: [               # at most top_n, ranked by effective weight desc
            {signal_id, side, conviction, weighted, author_id, source_slug,
             extracted_at, thesis_summary}
        ],
        contributing_authors: {author_id: count},
        contributing_sources: {source_slug: count},
      }
    """
    db_path = db_path or settings.sqlite_path
    now = now or datetime.now(UTC)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        allowed = seeded_author_ids(conn)
        rows = [dict(r) for r in conn.execute(
            """
            SELECT signal_id, side, conviction, weighted_score,
                   source_slug, source_channel, author_id,
                   source_trust_weight, author_trust_weight,
                   horizon, catalyst_type, thesis_summary,
                   extractor_name, extracted_at
            FROM signals
            WHERE asset_ticker = ?
              AND status = 'active'
              AND extracted_at >= datetime('now', '-' || ? || ' days')
            ORDER BY extracted_at DESC
            """,
            (ticker.upper(), since_days),
        ).fetchall()]
    # Only authors the user has explicitly stated count toward conviction.
    rows = [r for r in rows if (r.get("author_id") or "") in allowed]

    long_w = short_w = exit_w = 0.0
    watch_n = avoid_n = 0
    horizon_counts: dict[str, int] = {}
    catalyst_counts: dict[str, int] = {}
    author_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    ranked: list[tuple[float, dict]] = []

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
        a = row.get("author_id")
        if a:
            author_counts[a] = author_counts.get(a, 0) + 1
        src = row.get("source_slug")
        if src:
            source_counts[src] = source_counts.get(src, 0) + 1

        ranked.append((w, row))

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
        }
        for w, r in ranked[:top_n]
    ]

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

    dominant_horizon = max(horizon_counts, key=horizon_counts.get) if horizon_counts else None
    dominant_catalyst = max(catalyst_counts, key=catalyst_counts.get) if catalyst_counts else None

    return {
        "ticker": ticker.upper(),
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
        "dominant_horizon": dominant_horizon,
        "dominant_catalyst": dominant_catalyst,
        "top_signals": top_signals,
        "contributing_authors": author_counts,
        "contributing_sources": source_counts,
    }


def aggregate_for_tickers(
    tickers: Iterable[str],
    *,
    since_days: int = 90,
    half_life_days: float = 14.0,
    db_path: Optional[Path] = None,
) -> dict[str, dict]:
    """Batch convenience — one aggregate per ticker. Single connection."""
    out: dict[str, dict] = {}
    now = datetime.now(UTC)
    for t in tickers:
        out[t.upper()] = aggregate_for_ticker(
            t, since_days=since_days, half_life_days=half_life_days,
            now=now, db_path=db_path,
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

    Dynamic by design: the most-convicted tickers *this pass* define the
    top of the scale, so the component auto-calibrates as signal volume
    and conviction grow instead of relying on a hand-tuned constant.

    `percentile` (default 90th) of the nonzero |net_bias| across signaled
    tickers sets the level; `floor` keeps a thin/quiet pass from
    saturating on noise; `default` covers a pass with no signals at all.
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

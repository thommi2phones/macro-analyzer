"""Direction alerts — tell the operator where the read is going.

The rules in `rules.py` fire on the composite score crossing a band: the
number moved, so look. Useful, and staying exactly as it is. But the score
is a quality read, and quality moving is not the same as *direction*
moving. A ticker can hold an 84 for a week while the tape underneath it
quietly flips from long to short.

These rules watch the directional read instead, and say what changed in
the terms the operator would use to decide whether to open the chart:

    ETH · tape flipped LONG across 7d/28d
    Big_Nuts (55% setup win) and OG Whales (83%) both called it
    price sitting at a 4× zone last tested 23 bars ago (2,403)

That is the whole intent: this system notices direction and hands over the
context — the horizons that agree, who is behind it, and the structure
price is standing on. The operator charts it and places their own levels.
Nothing here proposes a trade.

Four triggers, all additive to the score-band alerts:

- **tape_flip** — the blended bias changed side, or a directional read
  emerged from neutral. Includes the early-warning case where the short
  horizons diverge from the long ones before the blend itself turns.
- **conviction_build** — same direction, materially more of it: more
  voices, harder calls. The "something is brewing" signal.
- **proven_voice_call** — a fresh call from an author whose setups
  actually resolve. Weighted by their backtested rate, so a proven voice
  pings and an unproven one does not.
- **zone_arrival** — price has reached a strong structure zone. The
  moment the chart is worth opening.

Scheduled passes only, same as `rules.py`: hand-run and what-if passes
would manufacture flips that never happened.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta

from macro_positioning.alerts.store import Alert

logger = logging.getLogger(__name__)

# --- thresholds -----------------------------------------------------------

# A flip is only news if the new read has some conviction behind it.
_FLIP_MIN_CONFIDENCE = 0.55

# Emerging from neutral needs more, since there is no prior side to contradict.
_EMERGE_MIN_CONFIDENCE = 0.60
_EMERGE_MIN_SIGNALS = 3

# Short horizons pulling away from long ones — the early warning.
_DIVERGENCE_MIN_CONFIDENCE = 0.60

# Conviction building, without a change of side.
_BUILD_MIN_CONFIDENCE_DELTA = 0.12
_BUILD_MIN_SIGNAL_DELTA = 3
_BUILD_MIN_SIGNALS = 4

# A voice worth waking someone up for.
_PROVEN_MIN_WIN_RATE = 0.60
_PROVEN_LOOKBACK_HOURS = 24

# Price is "at" a zone within this fraction of an ATR, and the zone has to
# be worth noticing. Both were looser on the first run and every ticker in
# the book qualified — 27 alerts in one cycle, which is a spam machine, not
# a notification.
_ZONE_ARRIVAL_ATR = 0.3
_ZONE_MIN_STRENGTH = 0.65

# Most zone arrivals worth sending in one cycle. Price sitting in a band
# for a week is one event, not seven, and a digest nobody reads is worse
# than no digest. Suppressed ones are logged, never silently dropped.
_MAX_ZONE_ALERTS = 5

_DIRECTIONAL = {"long", "short"}


# ---------------------------------------------------------------------------
# Pure decisions — unit-tested without a database
# ---------------------------------------------------------------------------

def detect_flip(prev: dict | None, curr: dict | None) -> dict | None:
    """Has the blended direction changed side, or emerged from neutral?

    Returns {kind, from, to, confidence} or None.
    """
    curr = curr or {}
    prev = prev or {}
    now_dir = (curr.get("bias_direction") or "").lower()
    was_dir = (prev.get("bias_direction") or "").lower()
    confidence = float(curr.get("bias_confidence") or 0.0)

    if now_dir not in _DIRECTIONAL:
        return None
    if was_dir in _DIRECTIONAL and was_dir != now_dir:
        if confidence >= _FLIP_MIN_CONFIDENCE:
            return {"kind": "flip", "from": was_dir, "to": now_dir,
                    "confidence": confidence}
        return None
    if was_dir not in _DIRECTIONAL:
        n = int(curr.get("n_signals") or 0)
        if confidence >= _EMERGE_MIN_CONFIDENCE and n >= _EMERGE_MIN_SIGNALS:
            return {"kind": "emerged", "from": was_dir or "neutral",
                    "to": now_dir, "confidence": confidence}
    return None


def detect_divergence(cross: dict | None) -> dict | None:
    """Short horizons pulling away from long ones, before the blend turns.

    This is the earliest honest warning the tape gives, and it is exactly
    the case a blend-only view averages away.
    """
    cross = cross or {}
    short = cross.get("short_bloc") or {}
    long_ = cross.get("long_bloc") or {}
    s_dir = (short.get("direction") or "").lower()
    l_dir = (long_.get("direction") or "").lower()
    if s_dir not in _DIRECTIONAL or l_dir not in _DIRECTIONAL:
        return None
    if s_dir == l_dir:
        return None
    if float(short.get("confidence") or 0.0) < _DIVERGENCE_MIN_CONFIDENCE:
        return None
    return {
        "short": s_dir, "long": l_dir,
        "confidence": float(short.get("confidence") or 0.0),
        "diverging": cross.get("diverging_windows") or [],
    }


def detect_build(prev: dict | None, curr: dict | None) -> dict | None:
    """More conviction in the same direction — no flip, just weight.

    Requires an actual directional read on both sides of the comparison,
    so "neutral gained a signal" never pages anyone.
    """
    curr = curr or {}
    prev = prev or {}
    now_dir = (curr.get("bias_direction") or "").lower()
    was_dir = (prev.get("bias_direction") or "").lower()
    if now_dir not in _DIRECTIONAL or now_dir != was_dir:
        return None

    c_now = float(curr.get("bias_confidence") or 0.0)
    c_was = float(prev.get("bias_confidence") or 0.0)
    n_now = int(curr.get("n_signals") or 0)
    n_was = int(prev.get("n_signals") or 0)
    if n_now < _BUILD_MIN_SIGNALS:
        return None

    d_conf = c_now - c_was
    d_n = n_now - n_was
    if d_conf < _BUILD_MIN_CONFIDENCE_DELTA and d_n < _BUILD_MIN_SIGNAL_DELTA:
        return None
    return {
        "direction": now_dir, "confidence": c_now,
        "confidence_delta": round(d_conf, 4),
        "n_signals": n_now, "signal_delta": d_n,
    }


def detect_zone_arrival(
    close: float | None,
    atr: float | None,
    zone,
    *,
    prev_close: float | None = None,
) -> dict | None:
    """Has price just ARRIVED at a level worth charting?

    Arrival, not residence: with `prev_close` given, the previous bar must
    have been outside the band. Price parked on a level for a fortnight is
    one event, and re-sending it every cycle trains the operator to ignore
    the channel.
    """
    if not close or not atr or atr <= 0 or zone is None:
        return None
    if zone.strength < _ZONE_MIN_STRENGTH:
        return None
    band = _ZONE_ARRIVAL_ATR * atr
    distance = abs(close - zone.price)
    if distance > band:
        return None
    if prev_close is not None and abs(prev_close - zone.price) <= band:
        return None  # already there last bar — not news
    return {
        "price": zone.price, "kind": zone.kind, "touches": zone.touches,
        "last_touch_bars": zone.last_touch_bars, "strength": zone.strength,
        "distance_pct": round(distance / close, 4), "basis": zone.basis,
    }


def _directional_side(blend: dict | None) -> str | None:
    """LONG/SHORT only. "NEUTRAL" in the side column reads as a call, and
    the digest's contract is to omit direction rather than guess it."""
    d = ((blend or {}).get("bias_direction") or "").lower()
    return d.upper() if d in _DIRECTIONAL else None


# ---------------------------------------------------------------------------
# Narrative — the sentence the operator reads on their phone
# ---------------------------------------------------------------------------

def agreeing_windows(windows: dict | None, direction: str) -> list[str]:
    """Which horizons carry this direction, tactical → thesis."""
    from macro_positioning.signals.aggregation import DEFAULT_WINDOWS

    order = [w[0] for w in DEFAULT_WINDOWS]
    windows = windows or {}
    return [
        label for label in order
        if (windows.get(label, {}).get("bias_direction") or "").lower() == direction
    ]


def describe_voices(voices: list[dict], limit: int = 3) -> str:
    """"Big_Nuts (55% setup win) and OG Whales (83%)" — who, and why they count."""
    if not voices:
        return ""
    parts = []
    for v in voices[:limit]:
        win = v.get("setup_win_rate")
        if v.get("meaningful") and win is not None:
            parts.append(f"{v['display_name']} ({win * 100:.0f}% setup win)")
        else:
            parts.append(f"{v['display_name']} (unproven)")
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + f" and {parts[-1]}"


def describe_zone(zone: dict | None) -> str:
    """"price at a 4× zone last tested 23 bars ago (2,403)"."""
    if not zone:
        return ""
    times = "once" if zone["touches"] == 1 else f"{zone['touches']}×"
    when = (
        "tested this bar" if zone["last_touch_bars"] <= 1
        else f"last tested {zone['last_touch_bars']} bars ago"
    )
    return f"price at a {times} {zone['kind']} zone, {when} ({zone['price']:.6g})"


def summarize_horizons(windows: list[str], *, total: int = 7) -> str:
    """"long across all 7 horizons" beats a seven-item list nobody parses."""
    if not windows:
        return ""
    if len(windows) >= total:
        return f"agreeing across all {total} horizons"
    return f"agreeing on {len(windows)} of {total}: {'/'.join(windows)}"


def compose_body(
    *,
    headline: str,
    windows: list[str],
    voices: list[dict],
    zone: dict | None,
    score: int | None = None,
    tier: str | None = None,
    total_windows: int = 7,
) -> str:
    """Assemble the alert body: what moved, across which horizons, who is
    behind it, and what price is standing on. Levels are deliberately
    absent — this hands over context, not a trade."""
    lines = [headline]
    if windows:
        lines.append(summarize_horizons(windows, total=total_windows))
    who = describe_voices(voices)
    if who:
        lines.append(f"called by {who}")
    z = describe_zone(zone)
    if z:
        lines.append(z)
    if score is not None:
        lines.append(f"composite {score}" + (f" · {tier}" if tier else ""))
    lines.append("chart it before acting — these are not trade levels")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Context gathering (DB)
# ---------------------------------------------------------------------------

def _load_pass_rows(
    conn: sqlite3.Connection, *, lookback_days: int = 14, as_of: str | None = None
) -> list[dict]:
    """Scheduled-pass rows carrying the signal aggregate, newest first."""
    rows = conn.execute(
        """
        SELECT a.ticker, ts.scored_at, ts.signal_aggregate_json,
               ts.adjusted_total_score, ts.position_size_tier, ts.score_id
        FROM trade_scores ts
        JOIN technical_setups tset ON tset.setup_id = ts.setup_id
        JOIN assets a ON a.asset_id = tset.asset_id
        WHERE ts.pass_kind IN ('scheduled', 'scheduled_delta')
          AND ts.scored_at >= datetime(COALESCE(?, 'now'), ?)
          AND (? IS NULL OR ts.scored_at <= ?)
        ORDER BY ts.scored_at DESC
        """,
        (as_of, f"-{int(lookback_days)} day", as_of, as_of),
    ).fetchall()
    out = []
    for r in rows:
        try:
            agg = json.loads(r[2]) if r[2] else {}
        except Exception:  # noqa: BLE001
            agg = {}
        out.append({
            "ticker": str(r[0]).upper(), "scored_at": r[1], "aggregate": agg,
            "score": r[3], "tier": r[4], "score_id": r[5],
        })
    return out


def _current_and_prior(rows: list[dict]) -> dict[str, tuple[dict, dict | None]]:
    """Newest row per ticker, paired with the one before it."""
    seen: dict[str, list[dict]] = {}
    for r in rows:  # already newest-first
        seen.setdefault(r["ticker"], []).append(r)
    return {t: (v[0], v[1] if len(v) > 1 else None) for t, v in seen.items()}


def recent_proven_voices(
    conn: sqlite3.Connection,
    ticker: str,
    *,
    weights: dict[str, dict],
    hours: int = _PROVEN_LOOKBACK_HOURS,
    now: datetime | None = None,
) -> list[dict]:
    """Fresh calls on this ticker from authors who resolve their setups."""
    now = now or datetime.now(UTC)
    cutoff = (now - timedelta(hours=hours)).isoformat()
    try:
        rows = conn.execute(
            """
            SELECT s.author_id, s.side, s.conviction, s.thesis_summary,
                   COALESCE(d.published_at, s.extracted_at) AS at
            FROM signals s
            LEFT JOIN documents d ON d.document_id = s.document_id
            WHERE s.asset_ticker = ?
              AND s.status = 'active'
              AND COALESCE(d.published_at, s.extracted_at) >= ?
            ORDER BY at DESC
            LIMIT 20
            """,
            (ticker.upper(), cutoff),
        ).fetchall()
    except sqlite3.OperationalError:
        return []

    out = []
    for author_id, side, conviction, thesis, at in rows:
        w = weights.get(author_id)
        if not w or not w.get("meaningful"):
            continue
        win = w.get("setup_win_rate")
        if win is None or win < _PROVEN_MIN_WIN_RATE:
            continue
        # Only directional calls. A proven voice saying AVOID is worth
        # knowing, but it is not "direction is going somewhere" — and
        # phrasing it as "called AVOID — 64% setup win rate" reads as a
        # setup recommendation, which is the opposite of its meaning.
        if (side or "").upper() not in {"LONG", "SHORT"}:
            continue
        out.append({
            "author_id": author_id, "display_name": w["display_name"],
            "setup_win_rate": win, "meaningful": True, "n_calls": w.get("n_calls"),
            "side": (side or "").upper(), "conviction": conviction,
            "thesis": thesis, "at": at,
        })
    return out


def voices_behind(
    conn: sqlite3.Connection, ticker: str, *, weights: dict[str, dict], atr: float | None
) -> list[dict]:
    """The trusted voices currently positioned in this ticker, heaviest first."""
    from macro_positioning.scoring.kol_levels import kol_levels_for_ticker

    try:
        kol = kol_levels_for_ticker(conn, ticker, atr=atr, weights=weights)
    except Exception:  # noqa: BLE001
        return []
    seen: dict[str, dict] = {}
    for consensus in (kol.entry, kol.target, kol.stop):
        for c in (consensus.contributors if consensus else []):
            if c.author_id not in seen:
                seen[c.author_id] = {
                    "display_name": c.display_name,
                    "setup_win_rate": c.setup_win_rate,
                    "meaningful": c.meaningful,
                    "weight": c.weight,
                }
    return sorted(seen.values(), key=lambda v: v["weight"], reverse=True)


def _zone_for(conn: sqlite3.Connection, ticker: str) -> tuple[dict | None, float | None, float | None]:
    """Nearest strong zone to current price, plus close and ATR."""
    from macro_positioning.prices.fetcher import load_recent_prices
    from macro_positioning.prices.structure import build_structure
    from macro_positioning.prices.technicals import compute_technical_features

    try:
        bars = load_recent_prices(ticker, days=200, conn=conn)
        feats = compute_technical_features(bars)
        close, atr = feats.get("close"), feats.get("atr14")
        structure = build_structure(bars, atr)
        prev_close = bars[-2].close if len(bars) >= 2 else None
    except Exception:  # noqa: BLE001
        return None, None, None
    if not close or not atr:
        return None, close, atr

    candidates = [
        lv for lv in structure.levels if lv.strength >= _ZONE_MIN_STRENGTH
    ]
    if not candidates:
        return None, close, atr
    nearest = min(candidates, key=lambda lv: abs(lv.price - close))
    return (
        detect_zone_arrival(close, atr, nearest, prev_close=prev_close),
        close,
        atr,
    )


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def evaluate(
    conn: sqlite3.Connection,
    *,
    cooldown_keys: set[tuple[str, str]] | None = None,
    as_of: str | None = None,
) -> list[Alert]:
    """Derive direction alerts for the newest scheduled pass.

    Mirrors `rules.evaluate`'s contract: returns Alerts, highest severity
    first, with (ticker, rule) pairs in `cooldown_keys` suppressed.
    """
    cooldown_keys = cooldown_keys or set()
    paired = _current_and_prior(_load_pass_rows(conn, as_of=as_of))
    if not paired:
        return []

    from macro_positioning.scoring.kol_levels import author_weights
    try:
        weights = author_weights()
    except Exception:  # noqa: BLE001
        weights = {}

    fired: list[Alert] = []

    def _blocked(ticker: str, rule: str) -> bool:
        return (ticker, rule) in cooldown_keys

    for ticker, (curr, prior) in paired.items():
        agg = curr["aggregate"] or {}
        blend = agg.get("blend") or {}
        prev_blend = (prior or {}).get("aggregate", {}).get("blend") or {}
        windows = agg.get("windows") or {}
        cross = agg.get("cross_window") or {}

        flip = detect_flip(prev_blend, blend)
        divergence = detect_divergence(cross) if not flip else None
        build = detect_build(prev_blend, blend) if not flip else None
        proven = recent_proven_voices(conn, ticker, weights=weights)

        # Only pay for structure on tickers that have something to say.
        zone = None
        if flip or divergence or build or proven:
            zone, _close, _atr = _zone_for(conn, ticker)
        elif not _blocked(ticker, "zone_arrival"):
            zone, _close, _atr = _zone_for(conn, ticker)

        voices = (
            voices_behind(conn, ticker, weights=weights, atr=None)
            if (flip or build) else []
        )

        if flip and not _blocked(ticker, "tape_flip"):
            direction = flip["to"]
            heads = (
                f"tape flipped {direction.upper()} (was {flip['from']})"
                if flip["kind"] == "flip"
                else f"{direction.upper()} read emerging from neutral"
            )
            fired.append(Alert(
                rule="tape_flip",
                severity="high" if flip["kind"] == "flip" else "medium",
                ticker=ticker,
                title=f"{ticker} · {heads}",
                body=compose_body(
                    headline=heads,
                    windows=agreeing_windows(windows, direction),
                    voices=voices or proven,
                    zone=zone,
                    score=curr.get("score"),
                    tier=curr.get("tier"),
                ),
                side=direction.upper(),
                score_after=curr.get("score"),
                tier_after=curr.get("tier"),
                score_id=curr.get("score_id"),
                payload={"flip": flip, "zone": zone, "cross_window": cross},
            ))

        if divergence and not _blocked(ticker, "horizon_divergence"):
            heads = (
                f"short horizons turning {divergence['short'].upper()} "
                f"against a {divergence['long'].upper()} thesis"
            )
            fired.append(Alert(
                rule="horizon_divergence", severity="medium", ticker=ticker,
                title=f"{ticker} · {heads}",
                body=compose_body(
                    headline=heads,
                    windows=divergence["diverging"],
                    voices=proven, zone=zone,
                    score=curr.get("score"), tier=curr.get("tier"),
                ),
                side=divergence["short"].upper(),
                score_after=curr.get("score"), tier_after=curr.get("tier"),
                score_id=curr.get("score_id"),
                payload={"divergence": divergence, "zone": zone},
            ))

        if build and not _blocked(ticker, "conviction_build"):
            heads = (
                f"{build['direction'].upper()} conviction building "
                f"({build['n_signals']} voices, "
                f"confidence {build['confidence'] * 100:.0f}%)"
            )
            fired.append(Alert(
                rule="conviction_build", severity="medium", ticker=ticker,
                title=f"{ticker} · {heads}",
                body=compose_body(
                    headline=heads,
                    windows=agreeing_windows(windows, build["direction"]),
                    voices=voices or proven, zone=zone,
                    score=curr.get("score"), tier=curr.get("tier"),
                ),
                side=build["direction"].upper(),
                score_after=curr.get("score"), tier_after=curr.get("tier"),
                score_id=curr.get("score_id"),
                payload={"build": build, "zone": zone},
            ))

        if proven and not _blocked(ticker, "proven_voice_call"):
            top = proven[0]
            heads = (
                f"{top['display_name']} called {top['side']} "
                f"— {top['setup_win_rate'] * 100:.0f}% setup win rate"
            )
            fired.append(Alert(
                rule="proven_voice_call",
                severity="high" if top["setup_win_rate"] >= 0.75 else "medium",
                ticker=ticker,
                title=f"{ticker} · {heads}",
                body=compose_body(
                    headline=heads,
                    windows=agreeing_windows(
                        windows, (blend.get("bias_direction") or "").lower()
                    ),
                    voices=proven, zone=zone,
                    score=curr.get("score"), tier=curr.get("tier"),
                ),
                side=top["side"] or None,
                score_after=curr.get("score"), tier_after=curr.get("tier"),
                score_id=curr.get("score_id"),
                payload={"voices": proven, "zone": zone},
            ))

        if zone and not (flip or divergence or build or proven) \
                and not _blocked(ticker, "zone_arrival"):
            heads = f"price reached a {zone['kind']} level worth charting"
            fired.append(Alert(
                rule="zone_arrival", severity="medium", ticker=ticker,
                title=f"{ticker} · {heads}",
                body=compose_body(
                    headline=heads,
                    windows=agreeing_windows(
                        windows, (blend.get("bias_direction") or "").lower()
                    ),
                    voices=[], zone=zone,
                    score=curr.get("score"), tier=curr.get("tier"),
                ),
                side=_directional_side(blend),
                score_after=curr.get("score"), tier_after=curr.get("tier"),
                score_id=curr.get("score_id"),
                payload={"zone": zone},
            ))

    # Cap the quietest rule so one broad market move can't bury the digest.
    # The cap is announced, not silent — a suppressed alert the operator
    # never hears about is indistinguishable from a rule that didn't fire.
    zones = [a for a in fired if a.rule == "zone_arrival"]
    if len(zones) > _MAX_ZONE_ALERTS:
        keep = sorted(
            zones,
            key=lambda a: (a.payload.get("zone") or {}).get("strength", 0),
            reverse=True,
        )[:_MAX_ZONE_ALERTS]
        dropped = [a.ticker for a in zones if a not in keep]
        logger.info(
            "direction alerts: %d zone arrivals suppressed by the per-cycle "
            "cap of %d (%s)", len(dropped), _MAX_ZONE_ALERTS, ", ".join(dropped),
        )
        fired = [a for a in fired if a.rule != "zone_arrival"] + keep

    order = {"high": 0, "medium": 1}
    fired.sort(key=lambda a: (order.get(a.severity, 9), a.ticker))
    return fired

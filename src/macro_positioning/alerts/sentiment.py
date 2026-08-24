"""What moved — directional sentiment across 1d / 3d / 7d / 14d.

The score tells you where a name stands. This tells you which way it is
turning, which is the earlier read: a name whose 1d and 3d blocs have
flipped against its 14d bloc is changing hands before the composite
score catches up.

Nothing is recomputed. `signals/aggregation.py` already produces the
7-window matrix and the scoring pass persists it whole into
`trade_scores.signal_aggregate_json`, so this reads the exact numbers
that produced the last score rather than a second opinion computed at a
different moment.

Comparability matters here. `net_bias` scales with call volume — BTC's
268 signals dwarf a name with 4 — so ranking on it would just re-rank by
popularity. The tilt used instead is `bias_confidence` signed by
`bias_direction`, which is bounded -1..+1 for every ticker regardless of
how loud its channel is.
"""

from __future__ import annotations

import json
import logging
import sqlite3

from macro_positioning.core.settings import settings

logger = logging.getLogger(__name__)

WINDOWS = ("1d", "3d", "7d", "14d")
_RECENT, _BASE = ("1d", "3d"), ("7d", "14d")

# A single call flipping is noise, not a shift.
_MIN_CALLS = 2
# Below this the "move" is rounding on a bounded scale.
_MIN_SHIFT = 0.15


def _tilt(window: dict | None) -> float | None:
    """Signed -1..+1 conviction, or None when the window holds no calls.

    None rather than 0.0 is the whole point. An empty window is silence,
    not neutrality, and collapsing the two inverts the reading: the first
    run of this scored ETH "turning bullish" off `+0.00 +0.00 -1.00
    -1.00` (it was bearish and then nobody spoke) and PLTR "turning
    bearish" off `+0.00 +0.00 +1.00 +1.00` (bullish, then silence). Both
    are the absence of a signal being reported as its reversal.
    """
    if not window or not int(window.get("n_signals") or 0):
        return None
    direction = str(window.get("bias_direction") or "").lower()
    confidence = float(window.get("bias_confidence") or 0.0)
    if direction == "long":
        return confidence
    if direction == "short":
        return -confidence
    return 0.0


def _mean(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def load_shifts(conn: sqlite3.Connection | None = None) -> dict:
    """Per-ticker sentiment trajectory from the most recent scored pass."""
    own = conn is None
    conn = conn or sqlite3.connect(f"file:{settings.sqlite_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            """
            WITH ranked AS (
              SELECT a.ticker AS ticker, ts.signal_aggregate_json AS agg,
                     ROW_NUMBER() OVER (
                       PARTITION BY a.ticker ORDER BY ts.scored_at DESC) AS rn
              FROM trade_scores ts
              JOIN technical_setups s ON s.setup_id = ts.setup_id
              JOIN assets a ON a.asset_id = s.asset_id
              WHERE ts.pass_kind LIKE 'scheduled%'
                AND ts.signal_aggregate_json IS NOT NULL)
            SELECT ticker, agg FROM ranked WHERE rn = 1
            """
        ).fetchall()
    finally:
        if own:
            conn.close()

    moved, quiet, thin = [], [], 0
    for ticker, raw in rows:
        try:
            agg = json.loads(raw)
        except Exception:  # noqa: BLE001
            continue
        windows = agg.get("windows") or {}
        if not windows:
            continue

        tilts = {w: _tilt(windows.get(w)) for w in WINDOWS}
        calls = int((windows.get("14d") or {}).get("n_signals") or 0)
        if calls < _MIN_CALLS:
            thin += 1
            continue

        recent = _mean([tilts[w] for w in _RECENT])
        base = _mean([tilts[w] for w in _BASE])

        if base is None:
            # Nothing to move away from.
            thin += 1
            continue
        if recent is None:
            # Coverage stopped. Real and worth knowing, but it is a
            # different fact from "sentiment reversed" and must not be
            # dressed up as one.
            quiet.append({"ticker": ticker, "tilts": tilts, "calls": calls,
                          "base": base})
            continue

        shift = recent - base
        if abs(shift) < _MIN_SHIFT:
            continue
        moved.append({
            "ticker": ticker,
            "tilts": tilts,
            "calls": calls,
            "recent": recent,
            "base": base,
            "shift": shift,
            # A flip is a change of side, not just of degree — the loudest
            # thing this can say, and worth separating from "more of the same".
            "flipped": bool(recent and base and (recent > 0) != (base > 0)),
        })

    moved.sort(key=lambda m: -abs(m["shift"]))
    quiet.sort(key=lambda q: -abs(q["base"]))
    return {"moved": moved, "quiet": quiet, "thin": thin, "scored": len(rows)}


def _cell(v: float | None) -> str:
    """'  —  ' for silence, so it never reads as a neutral score."""
    return "  —  " if v is None else f"{v:+.2f}"


def _side_word(v: float) -> str:
    return "long" if v > 0 else "short" if v < 0 else "neutral"


def _row(m: dict) -> str:
    cells = "  ".join(_cell(m["tilts"][w]) for w in WINDOWS)
    tail = f"{m['calls']} calls"
    if "base" in m and "recent" in m:
        # Name the side so "fading" is never mistaken for a reversal.
        tail = f"{_side_word(m['base'])} · {tail}"
    return f"  <b>{m['ticker']:<6}</b> {cells}   {tail}"


def build_message(data: dict | None = None) -> str | None:
    from macro_positioning.alerts.digest import _clip, _now_line

    data = data if data is not None else load_shifts()
    moved, quiet = data["moved"], data.get("quiet", [])
    if not moved and not quiet:
        return None

    header = [
        f"🔄 <b>Sentiment shift</b> · {' / '.join(WINDOWS)}",
        _now_line(),
        "<i>signed conviction per window, -1.00 short … +1.00 long</i>",
        "",
    ]
    # Classify by what actually changed, not by the sign of the delta.
    # A name going +1.00 -> +0.50 has a negative shift but is not bearish;
    # it is a long thesis losing conviction. Reporting that as "turning
    # bearish" invents a short nobody called — the same error as reading
    # silence as neutrality, one level subtler.
    flipped = [m for m in moved if m["flipped"]]
    rest = [m for m in moved if not m["flipped"]]
    stronger = [m for m in rest if abs(m["recent"]) > abs(m["base"])]
    fading = [m for m in rest if abs(m["recent"]) <= abs(m["base"])]

    lines: list[str] = []
    for label, bucket in (("⚠️ <b>FLIPPED SIDE</b>", flipped),
                          ("▲ <b>CONVICTION BUILDING</b>", stronger),
                          ("▽ <b>CONVICTION FADING</b>", fading)):
        if not bucket:
            continue
        lines.append(label)
        lines.extend(_row(m) for m in bucket)
        lines.append("")

    if quiet:
        lines.append("🔇 <b>WENT QUIET</b> <i>(no recent calls — not a reversal)</i>")
        lines.extend(_row(q) for q in quiet)
        lines.append("")

    # Say what was left out. A quiet board and a board we couldn't read
    # look identical otherwise.
    lines.append(
        f"<i>{data['scored']} scored · {len(moved)} moved · "
        f"{data['thin']} skipped (&lt;{_MIN_CALLS} calls in 14d)</i>"
    )
    return _clip(lines, header)

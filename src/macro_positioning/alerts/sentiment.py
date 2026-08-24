"""What moved — directional sentiment across 1d / 3d / 7d / 14d.

The score tells you where a name stands. This tells you which way it is
turning, which is the earlier read: a name whose 1d and 3d blocs have
flipped against its 14d bloc is changing hands before the composite
score catches up.

Computed fresh, deliberately. The 7-window matrix is persisted in
`trade_scores.signal_aggregate_json`, and reading it back looks cheaper
and more consistent — but the hourly watcher runs with
`skip_unchanged=True`, so a ticker whose *score* has not moved keeps its
old row. The aggregate can drift underneath a stable score, and on
2026-08-24 the latest row per ticker spanned 15 days: SOL reported 31
calls in its 14d window when the current value was 4. Sentiment is a
statement about now, so it is aggregated now, for every ticker at the
same instant and under the same code.

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


def _read(window: dict | None) -> tuple[float | None, str]:
    """(tilt, state) for one window.

    tilt is `bias_confidence` signed by direction: the share of the
    window's *directional* weight pointing one way, -1.00 (all short) to
    +1.00 (all long). It measures consensus, not force — one weak call
    alone reads +1.00 exactly like fifty strong ones, which is why the
    call count travels beside it on every row.

    None rather than 0.0 whenever there is no directional reading at all,
    and that covers two distinct cases the first draft collapsed into a
    misleading "+0.00":

      empty      — nobody spoke. Scored as 0.00 this inverted into a
                   reversal: ETH read "turning bullish" off
                   `+0.00 +0.00 -1.00 -1.00` when it was bearish and then
                   went silent.
      watch_only — people spoke but took no side. COIN's 1d window was a
                   single WATCH call; as 0.00 it dragged COIN into
                   "conviction fading" on the strength of someone
                   declining to call it.
    """
    if not window:
        return None, "empty"
    if not int(window.get("n_signals") or 0):
        return None, "empty"
    long_w = float(window.get("long_weight") or 0.0)
    short_w = float(window.get("short_weight") or 0.0)
    if long_w + short_w <= 0:
        # WATCH / AVOID / EXIT rows only — flagged, not called.
        return None, "watch_only"
    direction = str(window.get("bias_direction") or "").lower()
    confidence = float(window.get("bias_confidence") or 0.0)
    if direction == "long":
        return confidence, "directional"
    if direction == "short":
        return -confidence, "directional"
    return 0.0, "directional"


def _tilt(window: dict | None) -> float | None:
    return _read(window)[0]


def _mean(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def load_shifts(tickers: list[str] | None = None) -> dict:
    """Per-ticker sentiment trajectory, aggregated live."""
    from macro_positioning.scoring.watchlist_resolver import resolve_watchlist
    from macro_positioning.signals.aggregation import aggregate_for_tickers

    if tickers is None:
        resolved = resolve_watchlist(framework_regime="commodity_led_inflation")
        tickers = sorted({e.ticker for e in resolved.entries})
    aggregates = aggregate_for_tickers(tickers)

    moved, quiet, thin = [], [], 0
    for ticker in tickers:
        windows = (aggregates.get(ticker.upper()) or {}).get("windows") or {}
        if not windows:
            thin += 1
            continue

        reads = {w: _read(windows.get(w)) for w in WINDOWS}
        tilts = {w: reads[w][0] for w in WINDOWS}
        states = {w: reads[w][1] for w in WINDOWS}
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
            # Coverage stopped, or the recent calls took no side. Real and
            # worth knowing, but a different fact from "sentiment
            # reversed" and it must not be dressed up as one.
            quiet.append({"ticker": ticker, "tilts": tilts, "states": states,
                          "calls": calls, "base": base})
            continue

        shift = recent - base
        if abs(shift) < _MIN_SHIFT:
            continue
        moved.append({
            "ticker": ticker,
            "tilts": tilts,
            "states": states,
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
    return {"moved": moved, "quiet": quiet, "thin": thin, "scored": len(tickers)}


def _cell(v: float | None, state: str = "empty") -> str:
    """Never render a non-reading as a number.

    '  —  ' nobody spoke · ' wch ' spoke but took no side.
    """
    if v is not None:
        return f"{v:+.2f}"
    return " wch " if state == "watch_only" else "  —  "


def _side_word(v: float) -> str:
    return "long" if v > 0 else "short" if v < 0 else "neutral"


def _row(m: dict) -> str:
    states = m.get("states") or {}
    cells = "  ".join(
        _cell(m["tilts"][w], states.get(w, "empty")) for w in WINDOWS)
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
        "<i>share of directional weight: -1.00 all short … +1.00 all long</i>",
        "<i>— nobody spoke · wch spoke, no side taken</i>",
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
        lines.append("🔇 <b>NO RECENT SIDE</b> <i>(silent or watch-only — not a reversal)</i>")
        lines.extend(_row(q) for q in quiet)
        lines.append("")

    # Say what was left out. A quiet board and a board we couldn't read
    # look identical otherwise.
    lines.append(
        f"<i>{data['scored']} scored · {len(moved)} moved · "
        f"{data['thin']} skipped (&lt;{_MIN_CALLS} calls in 14d)</i>"
    )
    return _clip(lines, header)

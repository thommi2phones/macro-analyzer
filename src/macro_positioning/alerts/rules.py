"""Derive alerts from consecutive scoring passes.

The tracker's opinion is already in `trade_scores`. What was missing is
anything that notices the opinion *changed*. These rules do exactly that
and nothing more: they read two rows and decide whether the difference is
worth interrupting someone for.

Two rules ship today, both entry-side:

  grade_cross_a      — crossed into the A band (score >= 80)
  grade_cross_tier1  — crossed into the tier_1 band (score >= 85)
  score_jump         — gained >= `alert_score_jump` points in one step

They are separate rule names on purpose: each carries its own cooldown,
so "ETH is an A now" on Monday doesn't swallow "ETH is tier_1 now" on
Wednesday. That pair is precisely the August 2026 ETH sequence
(74 → 82 on the 17th, → 86 on the 20th).

Exit-side rules (stop breached, score collapse) are deliberately absent —
see the runner docstring.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from statistics import median

from macro_positioning.alerts.store import Alert
from macro_positioning.core.settings import settings

logger = logging.getLogger(__name__)


# Band edges from macro_brain.orchestrator.feature_vector.assign_grade /
# assign_position_size_tier. Duplicated as constants rather than imported
# so a change there is a visible test failure here, not a silent shift in
# what gets pushed to someone's phone.
A_BAND = 80
TIER1_BAND = 85
A_PLUS_BAND = 90

# Below the framework's own bands: a "worth a look" line drawn at 75.
# Not a grade boundary — B runs 70-79 — but the operator asked to hear
# about anything clearing 75, on the reasoning that a setup approaching
# A is worth eyeballing the chart for before it gets there. Fires at
# medium severity so it reads as a watch item, not a call to act.
WATCH_BAND = 75

# How far below a band a score must fall before that band can announce
# itself again. The August replay fired "LMT cleared 75 · 75" on the
# 18th, 20th and 22nd — a score parked on the line, dipping a point and
# popping back, each repeat just outside the 48h cooldown.
#
# Note this is a re-arm on the way OUT, not a filter on the way IN.
# Requiring the crossing itself to start from 3+ below was tried first
# and was worse than the disease: it silenced ETH's 78 → 82 cross into A
# on 2026-08-17 and BTC's 83 → 88 into tier_1 on the 21st, which are
# exactly the alerts this system exists to send. A band crossing normally
# *does* start just below the band; that's what makes it a crossing.
_REARM_MARGIN = 3

# Which read wins when one ticker trips several rules in the same cycle.
_RULE_PRIORITY = {
    "grade_cross_tier1": 4,
    "grade_cross_a": 3,
    "grade_cross_watch": 2,
    "score_jump": 1,
}


def _pass_key(setup_id: str) -> str:
    """Scoring passes stamp `setup-{ticker}-{run_id[:8]}`, so the trailing
    8 chars identify the pass exactly — better than bucketing `scored_at`
    by minute, which merges two passes that happen to straddle one.
    """
    return setup_id[-8:]


def _load_alertable_rows(
    conn: sqlite3.Connection,
    *,
    lookback_days: int = 30,
    as_of: str | None = None,
) -> list[dict]:
    """Scored rows from scheduled passes only, newest first.

    `pass_kind` is the gate. Hand-run and what-if passes write to the same
    table under a possibly-different regime, and comparing across the two
    kinds manufactures crossings that never happened.

    `as_of` (ISO timestamp) hides everything scored after it, so the rules
    can be replayed against history — "what would this have sent on
    2026-08-17?" — without mutating anything.
    """
    rows = conn.execute(
        """
        SELECT a.ticker, ts.scored_at, ts.adjusted_total_score, ts.grade,
               ts.position_size_tier, ts.score_id, ts.setup_id,
               ts.feature_vector_json, ts.pass_kind, ts.reasoning_trail_json
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
    return [{
        "ticker": str(r[0]).upper(), "scored_at": r[1], "score": r[2],
        "grade": r[3], "tier": r[4], "score_id": r[5],
        "pass_key": _pass_key(str(r[6])),
        "feature_vector_json": r[7], "pass_kind": r[8], "trail_json": r[9],
    } for r in rows]


def _complete_pass_keys(rows: list[dict]) -> set[str]:
    """Pass keys whose ticker count is close to the recent norm.

    A scheduled pass can still be partial — half the watchlist erroring
    out mid-run leaves a thin pass whose absent tickers look like nothing
    changed and whose present ones may be scored off stale inputs.

    Only `scheduled` (full-snapshot) passes are measured. The hourly
    watcher runs with skip_unchanged=True and writes `scheduled_delta`
    passes containing *only* the tickers that moved — a quiet hour is 3
    rows, which is thin by design, not by failure. Measuring those
    against the snapshot norm would discard exactly the passes the alert
    layer exists to read.
    """
    delta_keys = {r["pass_key"] for r in rows if r.get("pass_kind") == "scheduled_delta"}
    counts: dict[str, int] = {}
    for r in rows:
        if r["pass_key"] in delta_keys:
            continue
        counts[r["pass_key"]] = counts.get(r["pass_key"], 0) + 1
    if not counts:
        return delta_keys
    norm = median(counts.values())
    floor = norm * settings.alert_min_pass_completeness
    keep = {k for k, n in counts.items() if n >= floor} | delta_keys
    dropped = set(counts) - keep
    if dropped:
        logger.info(
            "ignoring %d partial pass(es) (median %d tickers, floor %.0f): %s",
            len(dropped), norm, floor,
            ", ".join(f"{k}={counts[k]}" for k in sorted(dropped)),
        )
    return keep


def _levels(row: dict) -> dict | None:
    try:
        fv = json.loads(row["feature_vector_json"]) if row["feature_vector_json"] else {}
    except Exception:  # noqa: BLE001
        return None
    lv = fv.get("levels")
    return lv if isinstance(lv, dict) else None


def _side(row: dict) -> str | None:
    """LONG / SHORT for the alert line, or None rather than a guess.

    Two sources, in order of what the operator would act on:

    1. `levels.side` — the side the technical agent actually laid rails
       on. This is the proposed trade, so it wins when it exists.
    2. `signal_bias.direction` — the tracked-voice consensus, used when
       no levels were synthesized (about 12 of 79 scored tickers).

    Returns None when neither is directional. `side_from_signal_bias`
    defaults to LONG whenever the voices aren't a confident short, so a
    fabricated "SHORT" is impossible here, but a missing read stays
    missing rather than being dressed up as a long.
    """
    lv = _levels(row)
    if lv and lv.get("side") in ("LONG", "SHORT"):
        return str(lv["side"])
    try:
        trail = json.loads(row["trail_json"]) if row.get("trail_json") else {}
    except Exception:  # noqa: BLE001
        return None
    direction = ((trail.get("signal_bias") or {}).get("direction") or "").lower()
    if direction in ("long", "short"):
        return direction.upper()
    return None


def _band_label(score: int) -> str:
    if score >= A_PLUS_BAND:
        return "A+"
    if score >= TIER1_BAND:
        return "A (tier_1)"
    if score >= A_BAND:
        return "A"
    if score >= WATCH_BAND:
        return "watch"
    return "below watch"


def _body(row: dict, prev: dict, *, headline: str) -> str:
    """The message the operator actually reads. Everything here has to
    earn its line: what changed, what the trade is, and where to look.
    """
    lines = [headline, ""]
    lines.append(
        f"Score {prev['score']} → {row['score']} "
        f"({prev['grade']} → {row['grade']}, {row['tier']})"
    )
    lv = _levels(row)
    if lv and lv.get("entry"):
        rr = lv.get("rr")
        lines.append(
            f"{lv.get('side', 'LONG')}  entry {lv['entry']:,.4g} · "
            f"stop {lv.get('stop', 0):,.4g} · target {lv.get('target', 0):,.4g}"
            + (f" · {rr:.1f}R" if isinstance(rr, (int, float)) else "")
        )
        if lv.get("setup"):
            lines.append(f"Setup: {lv['setup']}"
                         + ("" if lv.get("structural") else " (mechanical rails)"))
    else:
        lines.append("No levels synthesized — structure hasn't formed yet.")
    lines.append("")
    lines.append("Open the chart before acting. This is a prompt to look, not a trade.")
    return "\n".join(lines)


def evaluate(
    conn: sqlite3.Connection,
    *,
    cooldown_keys: set[tuple[str, str]] | None = None,
    as_of: str | None = None,
) -> list[Alert]:
    """Compare each ticker's two most recent alertable rows.

    `cooldown_keys` are (ticker, rule) pairs that fired recently and must
    be suppressed. Passed in rather than queried here so the rules stay a
    pure function of the score history.
    """
    cooldown_keys = cooldown_keys or set()
    rows = _load_alertable_rows(conn, as_of=as_of)
    if not rows:
        logger.info("no scheduled scoring rows in window — nothing to evaluate")
        return []

    complete = _complete_pass_keys(rows)
    rows = [r for r in rows if r["pass_key"] in complete]

    by_ticker: dict[str, list[dict]] = {}
    for r in rows:                      # already newest-first
        by_ticker.setdefault(r["ticker"], []).append(r)

    alerts: list[Alert] = []
    for ticker, history in by_ticker.items():
        if len(history) < 2:
            continue                    # no prior state = no transition
        now_row, prev_row = history[0], history[1]
        if now_row["score"] is None or prev_row["score"] is None:
            continue
        delta = now_row["score"] - prev_row["score"]

        def _emit(rule: str, severity: str, headline: str) -> None:
            # Cooldown is NOT applied here. A single move can trip several
            # bands at once (74 → 86 clears 75, 80 and 85); filtering by
            # cooldown before picking the winner would let a suppressed
            # grade_cross_a fall through and re-announce the same move as
            # a lower-band watch item.
            alerts.append(Alert(
                rule=rule,
                severity=severity,
                ticker=ticker,
                title=headline,
                body=_body(now_row, prev_row, headline=headline),
                score_before=prev_row["score"],
                score_after=now_row["score"],
                grade_before=prev_row["grade"],
                grade_after=now_row["grade"],
                tier_after=now_row["tier"],
                side=_side(now_row),
                score_id=now_row["score_id"],
                payload={
                    "levels": _levels(now_row),
                    "prev_scored_at": prev_row["scored_at"],
                    "scored_at": now_row["scored_at"],
                    "delta": delta,
                },
            ))

        def _crossed(band: int) -> bool:
            if not (prev_row["score"] < band <= now_row["score"]):
                return False
            # Find the last time this ticker was inside the band. If it
            # never dropped meaningfully below since, it never really
            # left, and re-announcing is noise.
            for j in range(1, len(history)):
                if (history[j]["score"] or 0) >= band:
                    trough = min(
                        (history[i]["score"] or 0) for i in range(1, j)
                    )
                    return trough <= band - _REARM_MARGIN
            return True     # no prior visit in the window — genuinely new

        # tier_1 first: when a move clears both bands at once this is the
        # more actionable of the two, and it takes the un-cooled slot.
        if _crossed(TIER1_BAND):
            _emit(
                "grade_cross_tier1", "high",
                f"{ticker} → {_band_label(now_row['score'])} · {now_row['score']}",
            )
        if _crossed(A_BAND):
            _emit(
                "grade_cross_a", "high",
                f"{ticker} crossed into A · {now_row['score']}",
            )
        if _crossed(WATCH_BAND):
            _emit(
                "grade_cross_watch", "medium",
                f"{ticker} cleared 75 · {now_row['score']}",
            )
        # A jump only earns an interrupt if it lands somewhere that could
        # plausibly become a trade — see alert_score_jump_min_score.
        if (
            delta >= settings.alert_score_jump
            and now_row["score"] >= settings.alert_score_jump_min_score
        ):
            _emit(
                "score_jump", "low",
                f"{ticker} jumped +{delta} to {now_row['score']}",
            )

    # One line per ticker per cycle. A move from 74 to 86 clears the 75,
    # 80 and 85 bands at once and would otherwise be announced three
    # times; a jump that also crosses a band is the same event described
    # twice. Keep the most actionable read, then apply cooldown to that
    # winner — in that order, so suppressing the loud read doesn't
    # promote a quieter description of the same move.
    best: dict[str, Alert] = {}
    for a in alerts:
        incumbent = best.get(a.ticker)
        if incumbent is None or _RULE_PRIORITY.get(a.rule, 0) > _RULE_PRIORITY.get(
            incumbent.rule, 0
        ):
            best[a.ticker] = a

    deduped = []
    for a in best.values():
        if (a.ticker, a.rule) in cooldown_keys:
            logger.info("suppressed %s/%s — inside cooldown", a.ticker, a.rule)
            continue
        deduped.append(a)

    # Highest conviction first, then biggest move — the send order, and
    # the order the digest truncates from the bottom of.
    _ORDER = {"high": 0, "medium": 1, "low": 2}
    deduped.sort(key=lambda a: (_ORDER.get(a.severity, 3), -(a.score_after or 0)))
    return deduped

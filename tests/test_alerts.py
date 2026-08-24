"""Alert derivation, suppression, and delivery shaping.

The regression this guards against is not "the code crashed" — it's the
tracker silently going quiet again, or getting so chatty it gets muted.
Both failure modes are noise-level bugs, so most of these tests are about
what *doesn't* fire.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from macro_positioning.alerts import notify, rules, store
from macro_positioning.db.schema import initialize_database


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "alerts.db"
    initialize_database(p)
    with sqlite3.connect(p) as c:
        yield c


def _score(
    db,
    ticker: str,
    score: int,
    *,
    ago_hours: int,
    pass_key: str,
    pass_kind: str = "scheduled",
    levels: dict | None = None,
) -> None:
    """Write one trade_scores row the way scoring/runner.py does."""
    from macro_brain.orchestrator.feature_vector import (
        assign_grade,
        assign_position_size_tier,
    )

    at = (datetime.now(UTC) - timedelta(hours=ago_hours)).isoformat()
    asset_id = f"asset-{ticker.lower()}"
    setup_id = f"setup-{ticker.lower()}-{pass_key}"
    db.execute(
        "INSERT OR IGNORE INTO assets (asset_id, ticker, asset_name, asset_class)"
        " VALUES (?, ?, ?, ?)",
        (asset_id, ticker, ticker, "crypto"),
    )
    db.execute(
        "INSERT OR IGNORE INTO technical_setups (setup_id, asset_id, observed_at,"
        " timeframe, setup_type, market_structure, technical_score)"
        " VALUES (?, ?, ?, '1D', 'watchlist_building', 'unknown', 0)",
        (setup_id, asset_id, at),
    )
    db.execute(
        """
        INSERT INTO trade_scores (
            score_id, setup_id, scored_at, regime_id,
            macro_alignment_score, liquidity_score, sector_theme_score,
            technical_structure_score, volume_flow_score, risk_reward_score,
            relative_strength_score, psychology_score,
            raw_total_score, adjusted_total_score, grade, position_size_tier,
            feature_vector_json, reasoning_trail_json, pass_kind
        ) VALUES (?, ?, ?, NULL, 0,0,0,0,0,0,0,0, ?, ?, ?, ?, ?, '{}', ?)
        """,
        (
            f"score-{ticker}-{pass_key}", setup_id, at, score, score,
            assign_grade(score),
            assign_position_size_tier(score, invalidation_defined=True),
            json.dumps({"levels": levels}) if levels else None,
            pass_kind,
        ),
    )
    db.commit()


def _rules_for(alerts):
    return {(a.ticker, a.rule) for a in alerts}


# ── firing ────────────────────────────────────────────────────────────

def test_cross_into_a_fires(db):
    """The August 2026 ETH sequence: 74 on the 19th, 82 on the 20th."""
    _score(db, "ETH", 74, ago_hours=24, pass_key="aaaaaaaa")
    _score(db, "ETH", 82, ago_hours=1, pass_key="bbbbbbbb")
    assert _rules_for(rules.evaluate(db)) == {("ETH", "grade_cross_a")}


def test_tier1_wins_when_one_step_clears_both_bands(db):
    """74 → 86 crosses A and tier_1 at once; that's one event, not two."""
    _score(db, "ETH", 74, ago_hours=24, pass_key="aaaaaaaa")
    _score(db, "ETH", 86, ago_hours=1, pass_key="bbbbbbbb")
    fired = rules.evaluate(db)
    assert _rules_for(fired) == {("ETH", "grade_cross_tier1")}
    assert len(fired) == 1


def test_no_alert_when_already_in_band(db):
    """Sitting at an A is not news — only the crossing is."""
    _score(db, "ETH", 87, ago_hours=24, pass_key="aaaaaaaa")
    _score(db, "ETH", 88, ago_hours=1, pass_key="bbbbbbbb")
    assert rules.evaluate(db) == []


def test_single_pass_ticker_has_no_prior_state(db):
    _score(db, "ETH", 95, ago_hours=1, pass_key="aaaaaaaa")
    assert rules.evaluate(db) == []


# ── suppression ───────────────────────────────────────────────────────

def test_score_jump_below_landing_floor_is_ignored(db):
    """'QQQ jumped +18 to 54' was two thirds of the replay's traffic."""
    _score(db, "QQQ", 36, ago_hours=24, pass_key="aaaaaaaa")
    _score(db, "QQQ", 54, ago_hours=1, pass_key="bbbbbbbb")
    assert rules.evaluate(db) == []


def test_score_jump_fires_when_it_lands_near_the_band(db):
    """59 → 76 both jumps and clears the watch band; the band crossing is
    the more informative read, so it wins the ticker's single slot."""
    _score(db, "XLK", 59, ago_hours=24, pass_key="aaaaaaaa")
    _score(db, "XLK", 76, ago_hours=1, pass_key="bbbbbbbb")
    assert _rules_for(rules.evaluate(db)) == {("XLK", "grade_cross_watch")}


def test_score_jump_wins_when_no_band_is_crossed(db):
    """A jump entirely inside the 75+ zone has no band to report."""
    _score(db, "XLK", 76, ago_hours=24, pass_key="aaaaaaaa")
    _score(db, "XLK", 79, ago_hours=1, pass_key="bbbbbbbb")
    assert rules.evaluate(db) == []          # +3 is not a jump
    _score(db, "GLD", 60, ago_hours=24, pass_key="aaaaaaaa")
    _score(db, "GLD", 79, ago_hours=1, pass_key="bbbbbbbb")
    assert ("GLD", "grade_cross_watch") in _rules_for(rules.evaluate(db))


def test_watch_band_fires_below_a(db):
    """The operator asked to hear about anything clearing 75."""
    _score(db, "SOL", 68, ago_hours=24, pass_key="aaaaaaaa")
    _score(db, "SOL", 77, ago_hours=1, pass_key="bbbbbbbb")
    fired = rules.evaluate(db)
    assert _rules_for(fired) == {("SOL", "grade_cross_watch")}
    assert fired[0].severity == "medium"


def test_shallow_dip_does_not_re_announce_a_band(db):
    """LMT sat on 75, dipped to 74, popped back to 79 — three times in the
    August replay, each just outside the 48h cooldown. It never left."""
    _score(db, "LMT", 76, ago_hours=96, pass_key="aaaaaaaa")
    _score(db, "LMT", 74, ago_hours=72, pass_key="bbbbbbbb")
    _score(db, "LMT", 79, ago_hours=1, pass_key="cccccccc")
    assert rules.evaluate(db) == []


def test_deep_exit_re_arms_the_band(db):
    """Same shape, but the score actually collapsed in between — that is a
    genuine re-entry and should be announced."""
    _score(db, "LMT", 76, ago_hours=96, pass_key="aaaaaaaa")
    _score(db, "LMT", 61, ago_hours=72, pass_key="bbbbbbbb")
    _score(db, "LMT", 79, ago_hours=1, pass_key="cccccccc")
    assert _rules_for(rules.evaluate(db)) == {("LMT", "grade_cross_watch")}


def test_crossing_from_just_below_the_band_still_fires(db):
    """ETH went 78 → 82 into A on 2026-08-17. A band crossing normally
    starts just below the band; suppressing that would silence the exact
    alert this system exists to send."""
    _score(db, "ETH", 78, ago_hours=24, pass_key="aaaaaaaa")
    _score(db, "ETH", 82, ago_hours=1, pass_key="bbbbbbbb")
    assert _rules_for(rules.evaluate(db)) == {("ETH", "grade_cross_a")}


def test_cooldown_does_not_promote_a_lower_band(db):
    """74 → 82 clears 75 and 80. If the A cross is on cooldown, the same
    move must not re-announce itself as a watch item."""
    _score(db, "ETH", 74, ago_hours=24, pass_key="aaaaaaaa")
    _score(db, "ETH", 82, ago_hours=1, pass_key="bbbbbbbb")
    assert rules.evaluate(db, cooldown_keys={("ETH", "grade_cross_a")}) == []


def test_cooldown_suppresses_a_repeat(db):
    _score(db, "ETH", 74, ago_hours=24, pass_key="aaaaaaaa")
    _score(db, "ETH", 82, ago_hours=1, pass_key="bbbbbbbb")
    assert rules.evaluate(db, cooldown_keys={("ETH", "grade_cross_a")}) == []


def test_manual_passes_are_not_alertable(db):
    """2026-08-21: hand-run passes under a different regime made ETH look
    like it round-tripped A→D→A in 90 minutes."""
    _score(db, "ETH", 74, ago_hours=24, pass_key="aaaaaaaa")
    _score(db, "ETH", 86, ago_hours=1, pass_key="bbbbbbbb", pass_kind="manual")
    assert rules.evaluate(db) == []


def test_partial_snapshot_pass_is_ignored(db):
    """A thin full-snapshot pass means a broken run, not a quiet market."""
    for i in range(12):
        _score(db, f"T{i}", 50, ago_hours=48, pass_key="aaaaaaaa")
        _score(db, f"T{i}", 50, ago_hours=24, pass_key="bbbbbbbb")
    # A 1-ticker 'scheduled' pass, far below the 12-ticker norm.
    _score(db, "T0", 95, ago_hours=1, pass_key="cccccccc")
    assert rules.evaluate(db) == []


def test_delta_pass_is_alertable_despite_being_thin(db):
    """The hourly watcher writes only what moved — thin by design. This is
    the bug that would have silenced every hourly alert."""
    for i in range(12):
        _score(db, f"T{i}", 50, ago_hours=48, pass_key="aaaaaaaa")
        _score(db, f"T{i}", 74, ago_hours=24, pass_key="bbbbbbbb")
    _score(db, "T0", 86, ago_hours=1, pass_key="cccccccc",
           pass_kind="scheduled_delta")
    assert _rules_for(rules.evaluate(db)) == {("T0", "grade_cross_tier1")}


# ── ordering + delivery shaping ───────────────────────────────────────

def test_high_severity_leads_the_batch(db):
    _score(db, "XLK", 59, ago_hours=24, pass_key="aaaaaaaa")
    _score(db, "XLK", 76, ago_hours=1, pass_key="bbbbbbbb")
    _score(db, "ETH", 74, ago_hours=24, pass_key="aaaaaaaa")
    _score(db, "ETH", 86, ago_hours=1, pass_key="bbbbbbbb")
    fired = rules.evaluate(db)
    assert [a.ticker for a in fired] == ["ETH", "XLK"]


def _fake_alerts(n: int) -> list[dict]:
    return [
        {"severity": "high", "ticker": f"T{i}", "title": f"T{i} crossed",
         "body": f"T{i} crossed\n\nScore 74 → 86", "score_before": 74,
         "score_after": 86, "grade_after": "A", "tier_after": "tier_1"}
        for i in range(n)
    ]


def test_board_wide_move_is_one_message_listing_every_name(monkeypatch):
    """2026-08-20 crossed 14 names at once off one regime flip. One
    message — but every name in it. An earlier cut hid the tail behind
    "…and 3 more", which buried names the operator wanted to see."""
    alerts = _fake_alerts(14)
    text = notify._format_digest(alerts)
    assert "14 setups moved" in text
    assert "more" not in text
    for i in range(14):
        assert f">T{i}<" in text


def test_digest_truncates_only_at_the_message_limit():
    """The one case a cap is still warranted: a message Telegram would
    reject outright. Drops from the bottom, i.e. lowest conviction."""
    text = notify._format_digest(_fake_alerts(400))
    assert len(text) <= notify._MAX_LEN
    assert "more (message limit)" in text
    assert ">T0<" in text          # highest conviction survives


def test_digest_header_carries_the_cycle_time():
    text = notify._format_digest(_fake_alerts(3))
    from datetime import datetime
    assert datetime.now().astimezone().strftime("%H:%M") in text


def test_single_alert_keeps_full_detail():
    alert = {
        "severity": "high", "ticker": "ETH", "title": "ETH crossed into A · 82",
        "body": "ETH crossed into A · 82\n\nScore 74 → 82 (B → A, tier_2)\n"
                "LONG  entry 2326 · stop 2187 · target 2743 · 3.0R",
        "score_before": 74, "score_after": 82,
        "grade_after": "A", "tier_after": "tier_2",
    }
    text = notify._format_digest([alert])
    assert "entry 2326" in text
    assert "setups moved" not in text


def test_digest_line_carries_asset_move_tier_and_direction(db):
    text = notify._digest_line({
        "severity": "high", "ticker": "ETH", "score_before": 74,
        "score_after": 86, "grade_after": "A", "tier_after": "tier_1",
        "side": "LONG",
    })
    assert "ETH" in text and "74→86" in text
    assert "A · tier_1" in text
    assert "LONG" in text


def test_green_is_highest_conviction_red_is_lowest():
    """Red-for-strongest read backwards to anyone who looks at markets."""
    def dot(sev):
        return notify._digest_line({
            "severity": sev, "ticker": "X", "score_before": 1, "score_after": 2,
            "grade_after": "A", "tier_after": "tier_1",
        })[0]
    assert dot("high") == "🟢"
    assert dot("medium") == "🟡"
    assert dot("low") == "🔴"


def test_direction_is_omitted_not_guessed():
    text = notify._digest_line({
        "severity": "high", "ticker": "ADM", "score_before": 74,
        "score_after": 82, "grade_after": "A", "tier_after": "tier_2",
        "side": None,
    })
    assert "LONG" not in text and "SHORT" not in text
    assert "ADM" in text


def test_side_comes_from_levels_then_voice_consensus(db):
    """levels.side is the proposed trade and wins; signal_bias.direction
    fills in when the technical agent produced no levels."""
    assert rules._side({
        "feature_vector_json": json.dumps({"levels": {"side": "SHORT"}}),
        "trail_json": json.dumps({"signal_bias": {"direction": "long"}}),
    }) == "SHORT"
    assert rules._side({
        "feature_vector_json": None,
        "trail_json": json.dumps({"signal_bias": {"direction": "long"}}),
    }) == "LONG"
    assert rules._side({
        "feature_vector_json": None,
        "trail_json": json.dumps({"signal_bias": {"direction": "neutral"}}),
    }) is None


def test_html_in_a_ticker_cannot_break_the_send():
    text = notify._format({
        "severity": "high", "ticker": "<b>", "title": "A & B <script>",
        "body": "A & B <script>\nline",
    })
    assert "<script>" not in text
    assert "&lt;script&gt;" in text


# ── store ─────────────────────────────────────────────────────────────

def test_delivery_state_round_trip(db):
    alert = store.Alert(rule="grade_cross_a", severity="high", ticker="ETH",
                        title="ETH crossed into A", body="body")
    store.record([alert], conn=db)

    pending = store.pending_delivery(window_hours=24, channel="telegram", conn=db)
    assert [a["alert_id"] for a in pending] == [alert.alert_id]

    store.mark_delivered(alert.alert_id, "telegram", "ok", conn=db)
    assert store.pending_delivery(window_hours=24, channel="telegram", conn=db) == []


def test_failed_delivery_is_retried(db):
    """An alert fired while the bot token was unset must still arrive
    once it's configured."""
    alert = store.Alert(rule="grade_cross_a", severity="high", ticker="ETH",
                        title="ETH crossed into A", body="body")
    store.record([alert], conn=db)
    store.mark_delivered(alert.alert_id, "telegram", "error: not configured", conn=db)
    pending = store.pending_delivery(window_hours=24, channel="telegram", conn=db)
    assert [a["alert_id"] for a in pending] == [alert.alert_id]


def test_cooldown_keys_reflect_recorded_fires(db):
    store.record([store.Alert(rule="grade_cross_a", severity="high",
                              ticker="eth", title="t", body="b")], conn=db)
    assert ("ETH", "grade_cross_a") in store.recent_fire_keys(hours=48, conn=db)

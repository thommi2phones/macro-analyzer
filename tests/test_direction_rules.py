"""Direction alerts — the decisions and the narrative (alerts/direction_rules.py)."""

from types import SimpleNamespace

from macro_positioning.alerts.direction_rules import (
    agreeing_windows,
    compose_body,
    describe_voices,
    describe_zone,
    detect_build,
    detect_divergence,
    detect_flip,
    detect_zone_arrival,
)


def _blend(direction="long", confidence=0.7, n=5):
    return {"bias_direction": direction, "bias_confidence": confidence, "n_signals": n}


def _zone(price=2403.0, kind="support", touches=4, last=23, strength=0.8):
    return SimpleNamespace(
        price=price, kind=kind, touches=touches, last_touch_bars=last,
        strength=strength, basis=f"{kind} {price:.4g}, held {touches}×",
    )


# --- flips --------------------------------------------------------------

def test_a_side_change_with_conviction_is_a_flip():
    got = detect_flip(_blend("short", 0.7), _blend("long", 0.7))
    assert got["kind"] == "flip"
    assert (got["from"], got["to"]) == ("short", "long")


def test_a_side_change_without_conviction_is_noise():
    assert detect_flip(_blend("short", 0.7), _blend("long", 0.4)) is None


def test_direction_emerging_from_neutral_is_reported_more_cautiously():
    got = detect_flip(_blend("neutral", 0.0, 0), _blend("long", 0.7, 5))
    assert got["kind"] == "emerged"


def test_emergence_needs_more_than_one_voice():
    assert detect_flip(_blend("neutral", 0.0, 0), _blend("long", 0.9, 1)) is None


def test_no_change_of_side_is_not_a_flip():
    assert detect_flip(_blend("long", 0.6), _blend("long", 0.9)) is None


def test_turning_neutral_is_not_a_flip():
    """Losing conviction isn't a direction — it's the absence of one."""
    assert detect_flip(_blend("long", 0.8), _blend("neutral", 0.2)) is None


# --- divergence (the early warning) -------------------------------------

def test_short_horizons_against_long_horizons_is_flagged():
    got = detect_divergence({
        "short_bloc": {"direction": "short", "confidence": 0.7},
        "long_bloc": {"direction": "long", "confidence": 0.6},
        "diverging_windows": ["1d", "3d"],
    })
    assert got["short"] == "short" and got["long"] == "long"


def test_agreement_across_horizons_is_not_divergence():
    assert detect_divergence({
        "short_bloc": {"direction": "long", "confidence": 0.8},
        "long_bloc": {"direction": "long", "confidence": 0.7},
    }) is None


def test_a_weak_short_bloc_does_not_warn():
    assert detect_divergence({
        "short_bloc": {"direction": "short", "confidence": 0.3},
        "long_bloc": {"direction": "long", "confidence": 0.7},
    }) is None


# --- conviction building ------------------------------------------------

def test_more_voices_in_the_same_direction_is_a_build():
    got = detect_build(_blend("long", 0.6, 4), _blend("long", 0.62, 8))
    assert got["signal_delta"] == 4
    assert got["direction"] == "long"


def test_rising_confidence_alone_is_a_build():
    got = detect_build(_blend("long", 0.55, 5), _blend("long", 0.75, 5))
    assert got["confidence_delta"] > 0


def test_a_flip_is_not_reported_as_a_build():
    assert detect_build(_blend("short", 0.6, 5), _blend("long", 0.9, 9)) is None


def test_a_thin_tape_does_not_build():
    """Two voices agreeing harder is not a signal."""
    assert detect_build(_blend("long", 0.5, 1), _blend("long", 0.9, 2)) is None


def test_drifting_confidence_is_not_worth_a_notification():
    assert detect_build(_blend("long", 0.60, 5), _blend("long", 0.63, 5)) is None


# --- zone arrival -------------------------------------------------------

def test_price_at_a_strong_zone_is_worth_charting():
    got = detect_zone_arrival(close=2400.0, atr=100.0, zone=_zone())
    assert got["touches"] == 4
    assert got["price"] == 2403.0


def test_price_far_from_the_zone_is_not_an_arrival():
    assert detect_zone_arrival(close=2000.0, atr=100.0, zone=_zone()) is None


def test_a_weak_zone_is_not_worth_the_ping():
    assert detect_zone_arrival(close=2400.0, atr=100.0, zone=_zone(strength=0.2)) is None


def test_missing_inputs_never_fire():
    assert detect_zone_arrival(None, 100.0, _zone()) is None
    assert detect_zone_arrival(2400.0, None, _zone()) is None
    assert detect_zone_arrival(2400.0, 100.0, None) is None


# --- the narrative ------------------------------------------------------

def test_agreeing_windows_come_back_tactical_to_thesis():
    windows = {
        "7d": {"bias_direction": "long"},
        "1d": {"bias_direction": "long"},
        "90d": {"bias_direction": "short"},
    }
    assert agreeing_windows(windows, "long") == ["1d", "7d"]


def test_voices_are_named_with_their_track_record():
    text = describe_voices([
        {"display_name": "Big_Nuts", "setup_win_rate": 0.55, "meaningful": True},
        {"display_name": "OG Whales", "setup_win_rate": 0.83, "meaningful": True},
    ])
    assert text == "Big_Nuts (55% setup win) and OG Whales (83% setup win)"


def test_unproven_voices_are_not_dressed_up():
    text = describe_voices([{"display_name": "New Guy", "setup_win_rate": None,
                             "meaningful": False}])
    assert "unproven" in text


def test_zone_description_reads_like_a_chart_note():
    text = describe_zone({
        "price": 2403.0, "kind": "support", "touches": 4, "last_touch_bars": 23,
    })
    assert "4×" in text and "support" in text and "23 bars ago" in text


def test_body_carries_the_context_and_no_trade_levels():
    body = compose_body(
        headline="tape flipped LONG (was short)",
        windows=["7d", "28d"],
        voices=[{"display_name": "Big_Nuts", "setup_win_rate": 0.55, "meaningful": True}],
        zone={"price": 2403.0, "kind": "support", "touches": 4, "last_touch_bars": 23},
        score=86, tier="tier_1",
    )
    assert "tape flipped LONG" in body
    assert "7d/28d" in body
    assert "Big_Nuts (55% setup win)" in body
    assert "2403" in body
    assert "composite 86" in body
    assert "chart it before acting" in body
    # The whole point: this hands over context, not an order ticket.
    for word in ("entry", "stop", "target", "R/R"):
        assert word.lower() not in body.lower().replace("chart it before acting — these are not trade levels", "")


def test_body_survives_missing_pieces():
    body = compose_body(headline="LONG read emerging from neutral",
                        windows=[], voices=[], zone=None)
    assert "LONG read emerging" in body
    assert "chart it" in body


# --- proven voices: only directional calls --------------------------------

def test_only_directional_calls_from_proven_voices_are_notified(tmp_path):
    """An AVOID from a good author is not "direction is going somewhere",
    and phrasing it as a called setup inverts its meaning."""
    import sqlite3

    from macro_positioning.alerts.direction_rules import recent_proven_voices

    db = tmp_path / "signals.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE signals (signal_id TEXT, asset_ticker TEXT, side TEXT,
            conviction REAL, thesis_summary TEXT, status TEXT,
            author_id TEXT, document_id TEXT, extracted_at TEXT);
        CREATE TABLE documents (document_id TEXT, published_at TEXT);
    """)
    conn.executemany(
        "INSERT INTO signals VALUES (?,?,?,?,?,'active',?,NULL,?)",
        [
            ("s1", "BTC", "AVOID", 3.0, "stay away", "a1", "2026-08-24T10:00:00+00:00"),
            ("s2", "BTC", "LONG", 4.0, "reclaim", "a1", "2026-08-24T11:00:00+00:00"),
            ("s3", "BTC", "WATCH", 2.0, "watching", "a1", "2026-08-24T11:30:00+00:00"),
        ],
    )
    conn.commit()

    weights = {"a1": {"display_name": "Proven", "setup_win_rate": 0.8,
                      "meaningful": True, "n_calls": 60, "weight": 0.8}}
    from datetime import UTC, datetime
    got = recent_proven_voices(
        conn, "BTC", weights=weights,
        now=datetime(2026, 8, 24, 12, 0, tzinfo=UTC),
    )
    assert [v["side"] for v in got] == ["LONG"]


def test_zone_residence_is_not_re_reported_every_cycle():
    """Price parked on a level is one event, not one per pass."""
    zone = _zone(price=100.0, strength=0.8)
    arrived = detect_zone_arrival(close=100.2, atr=4.0, zone=zone, prev_close=90.0)
    still_there = detect_zone_arrival(close=100.2, atr=4.0, zone=zone, prev_close=99.9)
    assert arrived is not None
    assert still_there is None


def test_horizon_summary_replaces_a_seven_item_list():
    from macro_positioning.alerts.direction_rules import summarize_horizons

    assert summarize_horizons(["1d", "3d", "7d", "14d", "28d", "90d", "180d"]) == \
        "agreeing across all 7 horizons"
    assert summarize_horizons(["1d", "7d"]) == "agreeing on 2 of 7: 1d/7d"
    assert summarize_horizons([]) == ""

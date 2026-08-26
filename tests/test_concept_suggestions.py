"""What earns a place in "suggested by system".

A suggestion is a claim that the desk could act on this name today, so
the rules that matter are the ones that keep un-actionable rows out:
placeholder levels on the scored side, and stale or already-blown calls
on the voice side.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from macro_positioning.dashboard import desk_data as dd
from macro_positioning.db.schema import initialize_database


def _scored_row(**over):
    row = {
        "asset": "COPX", "side": "LONG", "score": 75, "dScore": 0, "tier": 2,
        "regime": "off", "hasLevels": True, "rr": 5.53,
        "entry": 96.32, "stop": 93.0, "target": 114.64,
        "setup": "structure rails", "origins": ["anchor"], "whyNow": [],
        "levelStructural": True, "levelProvenance": [],
    }
    row.update(over)
    return row


@pytest.fixture
def db(isolate_database):
    # allow_reinit: conftest already redirected settings at this throwaway
    # file; see tests/test_funnel_suggestion_reviews.py for the same note.
    initialize_database(isolate_database, allow_reinit=True)
    return isolate_database


# ── scored stream ────────────────────────────────────────────────────────

def test_a_levelled_high_score_setup_is_suggested(db):
    out = dd.build_concept_suggestions_section([_scored_row()])
    assert [s["asset"] for s in out] == ["COPX"]
    assert out[0]["origin"] == "scored"
    assert "5.53R" in out[0]["reason"]
    assert "stop off market structure" in out[0]["reason"]


def test_mechanical_placeholder_levels_are_not_actionable(db):
    """2×ATR rails are the scorer's stand-in until structure forms —
    suggesting a trade off them is suggesting arithmetic."""
    out = dd.build_concept_suggestions_section(
        [_scored_row(levelStructural=False, levelProvenance=[])]
    )
    assert out == []


def test_a_trusted_voice_target_counts_as_a_real_level(db):
    row = _scored_row(levelStructural=False, levelProvenance=[
        {"role": "target", "source": "trusted_voices",
         "contributors": [{"display_name": "Big_Nuts"}, {"display_name": "Other"}]},
    ])
    out = dd.build_concept_suggestions_section([row])
    assert "target drawn by Big_Nuts +1" in out[0]["reason"]


def test_the_attribution_is_a_name_not_a_pasted_summary(db):
    row = _scored_row(levelStructural=False, levelProvenance=[
        {"role": "target", "source": "trusted_voices",
         "who": "Big_Nuts (55% setup win over 277 calls)"},
    ])
    assert "target drawn by Big_Nuts ·" in (
        dd.build_concept_suggestions_section([row])[0]["reason"] + " ·"
    )


@pytest.mark.parametrize("over", [
    {"score": dd.SUGGEST_SCORE_FLOOR - 1},
    {"tier": dd.SUGGEST_MAX_TIER + 1},
    {"rr": dd.SUGGEST_MIN_RR - 0.01},
    {"side": "WATCH"},
    {"hasLevels": False},
])
def test_rows_below_any_bar_are_left_out(db, over):
    assert dd.build_concept_suggestions_section([_scored_row(**over)]) == []


def test_names_already_being_worked_are_not_suggested_again(db):
    conn = sqlite3.connect(db)
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT INTO trade_concepts (concept_id, asset_id, source, status, "
        "suggested_by_system, marked_at, updated_at) "
        "VALUES ('c1', 'COPX', 'watchlist_manual', 'active', 0, ?, ?)",
        (now, now),
    )
    conn.commit()
    conn.close()
    assert dd.build_concept_suggestions_section([_scored_row()]) == []


def test_scored_names_rank_by_score_then_room(db):
    rows = [
        _scored_row(asset="AAA", score=75, rr=2.5),
        _scored_row(asset="BBB", score=88, rr=2.1),
        _scored_row(asset="CCC", score=75, rr=9.0),
    ]
    out = dd.build_concept_suggestions_section(rows)
    assert [s["asset"] for s in out] == ["BBB", "CCC", "AAA"]


# ── voice stream ─────────────────────────────────────────────────────────

def _seed_call(db, ticker, *, conviction=4.25, entry=32.99, stop=26.71,
               t1=39.88, t2=45.26, price=35.45, thesis="cup and handle",
               asset_class="equity", age_days=1):
    conn = sqlite3.connect(db)
    at = (datetime.now(UTC) - timedelta(days=age_days)).isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO input_authors (author_id, display_name, notes) "
        "VALUES ('feather-hands:big-nuts', 'Big_Nuts', 'seeded on first boot')"
    )
    conn.execute(
        """INSERT INTO signals (signal_id, document_id, extracted_at, asset_ticker,
           asset_class, side, conviction, entry_zone_low, stop_loss, target_1,
           target_2, thesis_summary, source_slug, source_channel, author_id,
           extractor_name, extractor_version, status)
           VALUES (?, 'doc', ?, ?, ?, 'LONG', ?, ?, ?, ?, ?, ?,
           'telegram', 'telegram-channel:ari_gold', 'feather-hands:big-nuts',
           'manual', 'test', 'active')""",
        (f"sig-{ticker}", at, ticker, asset_class, conviction, entry, stop, t1, t2, thesis),
    )
    if price is not None:
        conn.execute(
            "INSERT INTO prices (ticker, observed_at, timeframe, close, provider, "
            "fetched_at) VALUES (?, ?, '1d', ?, 'test', ?)",
            (ticker, datetime.now(UTC).date().isoformat(), price,
             datetime.now(UTC).isoformat()),
        )
    conn.commit()
    conn.close()


def test_a_live_call_on_an_unscored_name_is_surfaced(db):
    _seed_call(db, "PHYS")
    out = dd.build_concept_suggestions_section([])
    assert [s["asset"] for s in out] == ["PHYS"]
    row = out[0]
    assert row["origin"] == "voice"
    assert row["score"] is None          # never scored — that's the point
    assert row["conviction"] == 4.25
    assert "Big_Nuts" in row["reason"]


def test_a_name_the_watchlist_already_scores_is_left_to_the_scored_stream(db):
    _seed_call(db, "COPX")
    out = dd.build_concept_suggestions_section([_scored_row()])
    assert [(s["asset"], s["origin"]) for s in out] == [("COPX", "scored")]


def test_a_call_price_has_run_away_from_is_stale(db):
    """CCJ called at 15.47 while it trades at 106.96 is a chart annotation."""
    _seed_call(db, "CCJ", entry=15.47, stop=11.24, t1=23.09, t2=25.22, price=106.96)
    assert dd.build_concept_suggestions_section([]) == []


def test_a_call_whose_stop_is_already_gone_is_dropped(db):
    _seed_call(db, "PHYS", price=26.0)
    assert dd.build_concept_suggestions_section([]) == []


def test_a_call_that_has_eaten_most_of_its_risk_is_dropped(db):
    """Entry 32.99, stop 26.71, price 27.5 — 87% of the band is gone."""
    _seed_call(db, "PHYS", price=27.5)
    assert dd.build_concept_suggestions_section([]) == []


def test_a_stop_sitting_on_the_entry_is_an_artifact_not_a_trade(db):
    _seed_call(db, "BNB", entry=800, stop=791.97, t1=1124.94, t2=None, price=795)
    assert dd.build_concept_suggestions_section([]) == []


def test_an_unpriced_call_cannot_be_verified_so_it_is_not_suggested(db):
    """Gold called at 1264 would sail through on its own arithmetic."""
    _seed_call(db, "XAUUSD", entry=1264.59, stop=1183.61, t1=2039.8, t2=None,
               price=None)
    assert dd.build_concept_suggestions_section([]) == []


def test_dex_meme_pairs_stay_out_of_the_list(db):
    _seed_call(db, "YOLO/WETH", entry=0.009, stop=0.004, t1=0.02, t2=None,
               price=0.0095, thesis="solana memecoin launchpad", asset_class="crypto")
    assert dd.build_concept_suggestions_section([]) == []


def test_a_call_older_than_the_window_is_not_current_thinking(db):
    _seed_call(db, "PHYS", age_days=dd.SUGGEST_VOICE_MAX_AGE_DAYS + 2)
    assert dd.build_concept_suggestions_section([]) == []


def test_the_voice_tail_keeps_its_slots_against_a_full_scored_list(db):
    _seed_call(db, "PHYS")
    scored = [_scored_row(asset=f"S{i}", score=90 - i) for i in range(dd.SUGGEST_LIMIT + 4)]
    out = dd.build_concept_suggestions_section(scored)
    assert len(out) <= dd.SUGGEST_LIMIT
    assert out[-1]["asset"] == "PHYS"
    assert sum(1 for s in out if s["origin"] == "voice") == 1


def test_an_enormous_ratio_off_a_tight_stop_cannot_outrank_the_field(db):
    """Ranking R is capped: a 25R artifact must not lead the voice tail."""
    _seed_call(db, "PHYS", conviction=4.25)
    _seed_call(db, "CGNX", conviction=4.25, entry=62.16, stop=56.13,
               t1=107.69, t2=None, price=59.82)
    out = dd.build_concept_suggestions_section([])
    assert {s["asset"] for s in out} == {"PHYS", "CGNX"}
    assert all(s["rr"] is not None for s in out)

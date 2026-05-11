"""Tests for learning/source_attribution.py — both lenses."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from macro_positioning.db.schema import initialize_database
from macro_positioning.learning.source_attribution import (
    attribution,
    attribution_30d,
    attribution_90d,
    recommended_attribution_weights,
    signal_attribution,
    signal_history,
)


NOW = datetime(2026, 5, 9, 12, 0, 0, tzinfo=UTC)


def _conn(tmp_path: Path) -> sqlite3.Connection:
    db = tmp_path / "learn.db"
    initialize_database(db)
    return sqlite3.connect(db)


def _insert_outcome(conn, source_id: str, weight: float, pnl_pct: float, recorded_at: datetime, trade_id: str | None = None):
    # source_outcomes has FK to trades. Insert a stub trade row to satisfy.
    trade_id = trade_id or f"trade-{uuid.uuid4().hex[:8]}"
    asset_id = f"asset-{uuid.uuid4().hex[:8]}"
    conn.execute(
        "INSERT OR IGNORE INTO assets (asset_id, ticker, asset_name, asset_class) VALUES (?,?,?,?)",
        (asset_id, "TST", "Test", "equity"),
    )
    conn.execute(
        """INSERT INTO trades (trade_id, asset_id, entry_date, entry_price, position_size, stop_loss, status)
           VALUES (?,?,?,?,?,?,?)""",
        (trade_id, asset_id, recorded_at.isoformat(), 100.0, 1.0, 95.0, "closed"),
    )
    conn.execute(
        """INSERT INTO source_outcomes (
              outcome_id, source_id, trade_id, attribution_weight,
              outcome_pnl, outcome_pnl_percent, recorded_at
           ) VALUES (?,?,?,?,?,?,?)""",
        (f"o-{uuid.uuid4().hex[:8]}", source_id, trade_id, weight, None, pnl_pct, recorded_at.isoformat()),
    )


# ---------------------------------------------------------------------------
# 1a — closed-trade lens
# ---------------------------------------------------------------------------

def test_attribution_empty_returns_empty_list(tmp_path: Path):
    conn = _conn(tmp_path)
    assert attribution(conn) == []
    assert attribution_30d(conn) == []
    assert attribution_90d(conn) == []


def test_attribution_aggregates_per_source_and_sorts_by_weighted(tmp_path: Path):
    conn = _conn(tmp_path)
    # Source A: two outcomes, +10% (w=1.0), -2% (w=0.5)
    _insert_outcome(conn, "src_a", 1.0, 10.0, NOW - timedelta(days=2))
    _insert_outcome(conn, "src_a", 0.5, -2.0, NOW - timedelta(days=5))
    # Source B: one outcome, +4% (w=1.0)
    _insert_outcome(conn, "src_b", 1.0, 4.0, NOW - timedelta(days=1))
    conn.commit()

    # recency_half_life_days=0 disables the v2 read-side decay so we
    # can assert the pure stored-weight math here.
    rows = attribution(conn, window_days=30, recency_half_life_days=0, now=NOW)
    by_id = {r["source_id"]: r for r in rows}
    assert by_id["src_a"]["n_outcomes"] == 2
    assert by_id["src_a"]["total_pnl_pct"] == pytest.approx(8.0)
    assert by_id["src_a"]["avg_pnl_pct"] == pytest.approx(4.0)
    # Weighted: (10*1.0 + -2*0.5) / 1.5 = 9/1.5 = 6.0
    assert by_id["src_a"]["weighted_pnl_pct"] == pytest.approx(6.0)
    # src_a (6.0) > src_b (4.0) → first
    assert rows[0]["source_id"] == "src_a"


def test_attribution_recency_decay_favors_fresh_contributions(tmp_path: Path):
    """Two sources, same stored weight, same |pnl|, opposite sign.
    Recency decay should pull the leaderboard toward the fresher one."""
    conn = _conn(tmp_path)
    _insert_outcome(conn, "src_fresh", 1.0, 10.0, NOW - timedelta(days=1))
    _insert_outcome(conn, "src_stale", 1.0, 10.0, NOW - timedelta(days=25))
    conn.commit()

    # half-life 5d → 25d-old row counts at 0.5^5 ≈ 0.031
    rows = attribution(conn, window_days=30, recency_half_life_days=5, now=NOW)
    by_id = {r["source_id"]: r for r in rows}
    assert by_id["src_fresh"]["sum_effective_weight"] > by_id["src_stale"]["sum_effective_weight"] * 10
    # Both sources earned the same pnl% per row → weighted_pnl_pct equal,
    # but the *effective weight* tells the dashboard who matters more.
    assert by_id["src_fresh"]["sum_stored_weight"] == pytest.approx(1.0)
    assert by_id["src_stale"]["sum_stored_weight"] == pytest.approx(1.0)


def test_attribution_include_meta_returns_diagnostic_on_empty(tmp_path: Path):
    conn = _conn(tmp_path)
    out = attribution(conn, include_meta=True)
    assert isinstance(out, dict)
    assert out["rows"] == []
    assert out["_meta"]["rows_in_table_total"] == 0
    assert "feedback_writer hasn't fired yet" in out["_meta"]["message"]


def test_attribution_include_meta_returns_summary_on_populated(tmp_path: Path):
    conn = _conn(tmp_path)
    _insert_outcome(conn, "src_a", 1.0, 5.0, NOW - timedelta(days=1))
    conn.commit()
    out = attribution(conn, include_meta=True, now=NOW)
    assert out["_meta"]["n_sources"] == 1
    assert out["_meta"]["rows_in_window"] == 1


def test_recommended_attribution_weights_equal_split_fallback():
    w = recommended_attribution_weights(["a", "b", "c"])
    # No mention_age_days passed → all sources get half-life-aged weight
    # of 0.5 → normalized to 1/3 each.
    assert sum(w.values()) == pytest.approx(1.0)
    assert w["a"] == pytest.approx(w["b"]) == pytest.approx(w["c"])


def test_recommended_attribution_weights_recency_favors_fresh():
    w = recommended_attribution_weights(
        ["fresh", "stale"],
        mention_age_days={"fresh": 0.0, "stale": 28.0},
        half_life_days=14.0,
    )
    assert w["fresh"] > w["stale"]
    assert sum(w.values()) == pytest.approx(1.0)
    # fresh (age 0 → weight 1.0) vs stale (age 28 → weight 0.25)
    # → fresh / total = 1.0 / 1.25 = 0.8
    assert w["fresh"] == pytest.approx(0.8, abs=0.01)


def test_recommended_attribution_weights_empty():
    assert recommended_attribution_weights([]) == {}


def test_attribution_window_excludes_old_rows(tmp_path: Path):
    conn = _conn(tmp_path)
    _insert_outcome(conn, "src_a", 1.0, 50.0, NOW - timedelta(days=60))  # outside 30d
    _insert_outcome(conn, "src_a", 1.0, 5.0, NOW - timedelta(days=10))   # inside
    conn.commit()
    rows30 = attribution(conn, window_days=30, now=NOW)
    rows90 = attribution(conn, window_days=90, now=NOW)
    assert len(rows30) == 1 and rows30[0]["n_outcomes"] == 1
    assert rows30[0]["avg_pnl_pct"] == pytest.approx(5.0)
    assert len(rows90) == 1 and rows90[0]["n_outcomes"] == 2


# ---------------------------------------------------------------------------
# 1b — expression trend lens
# ---------------------------------------------------------------------------

def _insert_doc(conn, source_id: str, published_at: datetime, text: str, doc_id: str | None = None):
    doc_id = doc_id or f"doc-{uuid.uuid4().hex[:8]}"
    conn.execute(
        """INSERT INTO documents (document_id, source_id, title, url, published_at,
              author, content_type, raw_text, cleaned_text, tags_json, ingested_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            doc_id, source_id, "title", None, published_at.isoformat(),
            None, "article", text, text, "[]", published_at.isoformat(),
        ),
    )


def _insert_price(conn, ticker: str, observed_at: datetime, close: float):
    conn.execute(
        """INSERT OR REPLACE INTO prices
           (price_id, ticker, observed_at, timeframe, open, high, low, close, volume, provider, fetched_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            f"p-{uuid.uuid4().hex[:8]}", ticker,
            observed_at.date().isoformat(), "1D",
            close, close, close, close, 0, "test", NOW.isoformat(),
        ),
    )


def test_signal_attribution_empty_returns_empty(tmp_path: Path):
    conn = _conn(tmp_path)
    assert signal_attribution(conn) == []


def test_signal_attribution_grades_each_mention_against_forward_return(tmp_path: Path):
    conn = _conn(tmp_path)
    pub = NOW - timedelta(days=120)

    # Source A mentions URA in two docs. URA goes from 100 → 110 over 30d (+10%).
    _insert_doc(conn, "src_a", pub, "We like URA here at the bottom of the cycle")
    _insert_doc(conn, "src_a", pub + timedelta(days=2), "URA still leads")
    # Provide daily-ish bars so on/before and on/after lookups succeed.
    _insert_price(conn, "URA", pub - timedelta(days=1), 100.0)
    _insert_price(conn, "URA", pub, 100.0)
    _insert_price(conn, "URA", pub + timedelta(days=2), 100.5)
    _insert_price(conn, "URA", pub + timedelta(days=30), 110.0)
    _insert_price(conn, "URA", pub + timedelta(days=32), 110.0)
    _insert_price(conn, "URA", pub + timedelta(days=33), 110.0)
    _insert_price(conn, "URA", pub + timedelta(days=40), 110.0)
    conn.commit()

    rows = signal_attribution(conn, horizons=(30,))
    assert len(rows) == 1
    row = rows[0]
    assert row["source_id"] == "src_a"
    assert row["n_signals"] == 2
    h30 = row["horizons"][30]
    assert h30["n_with_price_data"] == 2
    # Both mentions saw a positive forward return → hit_rate 1.0
    assert h30["hit_rate"] == pytest.approx(1.0)
    # avg forward return ≈ +10% (rounded)
    assert h30["avg_forward_return_pct"] > 5.0


def test_signal_attribution_skips_mentions_without_price_data(tmp_path: Path):
    conn = _conn(tmp_path)
    # URA mentioned but no prices table entry — should still count as
    # a signal but n_with_price_data stays 0.
    _insert_doc(conn, "src_a", NOW - timedelta(days=60), "watching URA closely")
    conn.commit()
    rows = signal_attribution(conn, horizons=(30,))
    assert len(rows) == 1
    assert rows[0]["n_signals"] == 1
    assert rows[0]["horizons"][30]["n_with_price_data"] == 0


def test_signal_attribution_decay_weighted_sort_demotes_stale_one_hit_wonders(tmp_path: Path):
    """A one-shot perfect call should rank below a higher-volume hit-rate
    leader once decay + log(1+n) are applied."""
    conn = _conn(tmp_path)
    # src_oneshot: single +10% call from 200d ago
    pub_stale = NOW - timedelta(days=200)
    _insert_doc(conn, "src_oneshot", pub_stale, "URA looks great")
    _insert_price(conn, "URA", pub_stale - timedelta(days=1), 100.0)
    _insert_price(conn, "URA", pub_stale, 100.0)
    _insert_price(conn, "URA", pub_stale + timedelta(days=30), 110.0)
    _insert_price(conn, "URA", pub_stale + timedelta(days=33), 110.0)

    # src_consistent: 6 +2% calls from the last 10 days (recent + high volume + perfect hit-rate)
    for i in range(6):
        pub = NOW - timedelta(days=10 - i)
        _insert_doc(conn, "src_consistent", pub, f"BTC bullish #{i}", doc_id=f"d-bc-{i}")
        _insert_price(conn, "BTC", pub - timedelta(days=1), 50000.0)
        _insert_price(conn, "BTC", pub, 50000.0)
        _insert_price(conn, "BTC", pub + timedelta(days=30), 51000.0)
        _insert_price(conn, "BTC", pub + timedelta(days=33), 51000.0)
    conn.commit()

    # raw_return mode: oneshot's +10% beats consistent's +2% per-call
    rows_raw = signal_attribution(conn, horizons=(30,), sort_mode="raw_return")
    assert rows_raw[0]["source_id"] == "src_oneshot"

    # decay_weighted mode: 200d-old solo hit gets crushed by the recent stack
    rows_decay = signal_attribution(conn, horizons=(30,), sort_mode="decay_weighted", now=NOW)
    assert rows_decay[0]["source_id"] == "src_consistent"
    # And the new score field is exposed on each row
    assert "decay_weighted_score" in rows_decay[0]
    # Consistent's score must be strictly higher
    consistent_score = next(r["decay_weighted_score"] for r in rows_decay if r["source_id"] == "src_consistent")
    oneshot_score = next(r["decay_weighted_score"] for r in rows_decay if r["source_id"] == "src_oneshot")
    assert consistent_score > oneshot_score


def test_signal_attribution_sort_mode_validation(tmp_path: Path):
    conn = _conn(tmp_path)
    with pytest.raises(ValueError):
        signal_attribution(conn, sort_mode="bogus")


def test_signal_attribution_breaks_out_per_vertical(tmp_path: Path):
    """Source mentions URA (commodity) and SPY (index). v2 must give
    per-vertical hit-rate + return per horizon.
    URA: 100 → 110 (+10%) — commodity hits.
    SPY: 400 → 380 (-5%) — index misses.
    """
    conn = _conn(tmp_path)
    pub = NOW - timedelta(days=120)

    _insert_doc(conn, "src_a", pub, "URA looks great, SPY is rolling over")
    # URA price path
    _insert_price(conn, "URA", pub - timedelta(days=1), 100.0)
    _insert_price(conn, "URA", pub, 100.0)
    _insert_price(conn, "URA", pub + timedelta(days=30), 110.0)
    _insert_price(conn, "URA", pub + timedelta(days=33), 110.0)
    # SPY price path
    _insert_price(conn, "SPY", pub - timedelta(days=1), 400.0)
    _insert_price(conn, "SPY", pub, 400.0)
    _insert_price(conn, "SPY", pub + timedelta(days=30), 380.0)
    _insert_price(conn, "SPY", pub + timedelta(days=33), 380.0)
    conn.commit()

    rows = signal_attribution(conn, horizons=(30,))
    assert len(rows) == 1
    h30 = rows[0]["horizons"][30]
    by_v = h30["by_vertical"]
    assert "commodity" in by_v and "index" in by_v
    assert by_v["commodity"]["hit_rate"] == pytest.approx(1.0)
    assert by_v["commodity"]["avg_forward_return_pct"] > 5.0
    assert by_v["index"]["hit_rate"] == pytest.approx(0.0)
    assert by_v["index"]["avg_forward_return_pct"] < 0.0
    # Source row carries ticker_verticals for quick top-N display
    assert set(rows[0]["ticker_verticals"]) >= {"commodity", "index"}


def test_signal_attribution_include_meta(tmp_path: Path):
    conn = _conn(tmp_path)
    out = signal_attribution(conn, include_meta=True)
    assert isinstance(out, dict)
    assert out["rows"] == []
    assert out["_meta"]["n_documents"] == 0
    assert "no documents" in out["_meta"]["message"]


def test_signal_history_buckets_by_month(tmp_path: Path):
    conn = _conn(tmp_path)
    pub_jan = datetime(2026, 1, 15, tzinfo=UTC)
    pub_feb = datetime(2026, 2, 15, tzinfo=UTC)
    _insert_doc(conn, "src_a", pub_jan, "URA looks good")
    _insert_doc(conn, "src_a", pub_feb, "URA again")
    for d, p in [(pub_jan, 100.0), (pub_jan + timedelta(days=30), 105.0),
                 (pub_feb, 200.0), (pub_feb + timedelta(days=30), 190.0)]:
        _insert_price(conn, "URA", d, p)
    conn.commit()

    hist = signal_history(conn, "src_a", horizon=30)
    assert [b["bucket"] for b in hist] == ["2026-01", "2026-02"]
    # Jan: +5% return, hit; Feb: -5% return, miss.
    assert hist[0]["hit_rate"] == pytest.approx(1.0)
    assert hist[1]["hit_rate"] == pytest.approx(0.0)

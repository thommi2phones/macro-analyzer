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

    rows = attribution(conn, window_days=30, now=NOW)
    by_id = {r["source_id"]: r for r in rows}
    assert by_id["src_a"]["n_outcomes"] == 2
    assert by_id["src_a"]["total_pnl_pct"] == pytest.approx(8.0)
    assert by_id["src_a"]["avg_pnl_pct"] == pytest.approx(4.0)
    # Weighted: (10*1.0 + -2*0.5) / 1.5 = 9/1.5 = 6.0
    assert by_id["src_a"]["weighted_pnl_pct"] == pytest.approx(6.0)
    # src_a (6.0) > src_b (4.0) → first
    assert rows[0]["source_id"] == "src_a"


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

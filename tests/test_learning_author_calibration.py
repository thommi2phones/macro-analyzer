"""Tests for learning/author_calibration.py — R1 + R2."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from macro_positioning.db.schema import initialize_database
from macro_positioning.learning.author_calibration import (
    author_attribution,
    conviction_calibration,
)


NOW = datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC)


def _conn(tmp_path: Path) -> sqlite3.Connection:
    db = tmp_path / "ac.db"
    initialize_database(db)
    return sqlite3.connect(db)


def _insert_author(conn, author_id: str, display_name: str):
    conn.execute(
        """INSERT OR IGNORE INTO input_authors
              (author_id, display_name, channel, channel_type, notes,
               first_seen_at, last_seen_at)
           VALUES (?,?,?,?,?,?,?)""",
        (author_id, display_name, "self", "self", None, NOW.isoformat(), NOW.isoformat()),
    )


def _insert_manual_doc(
    conn,
    *,
    author_id: str,
    published_at: datetime,
    text: str,
    conviction: int | None = None,
    doc_id: str | None = None,
):
    doc_id = doc_id or f"doc-{uuid.uuid4().hex[:8]}"
    user_meta = {
        "user": {
            "ticker": None,
            "side": None,
            "conviction": conviction,
            "timeframe": None,
            "note": None,
        },
        "resolved": {},
        "channel": "self",
        "channel_type": "self",
    }
    conn.execute(
        """INSERT INTO documents (
              document_id, source_id, title, url, published_at, author,
              content_type, raw_text, cleaned_text, tags_json, ingested_at,
              author_id, user_metadata_json
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            doc_id,
            f"manual:{author_id}",
            "manual",
            None,
            published_at.isoformat(),
            author_id,
            "manual_note",
            text,
            text,
            "[]",
            published_at.isoformat(),
            author_id,
            json.dumps(user_meta),
        ),
    )


def _insert_price(conn, ticker: str, observed_at: datetime, close: float):
    conn.execute(
        """INSERT OR REPLACE INTO prices
           (price_id, ticker, observed_at, timeframe, open, high, low, close, volume, provider, fetched_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            f"p-{uuid.uuid4().hex[:8]}",
            ticker,
            observed_at.date().isoformat(),
            "1D",
            close,
            close,
            close,
            close,
            0,
            "test",
            NOW.isoformat(),
        ),
    )


def _price_path(conn, ticker: str, pub: datetime, entry: float, exit_: float):
    """Bracket a doc's published_at with enough bars to satisfy
    `_close_at_or_before` (at/before pub) and `_close_at_or_after`
    (at/after pub + horizon)."""
    _insert_price(conn, ticker, pub - timedelta(days=1), entry)
    _insert_price(conn, ticker, pub, entry)
    _insert_price(conn, ticker, pub + timedelta(days=30), exit_)
    _insert_price(conn, ticker, pub + timedelta(days=33), exit_)
    _insert_price(conn, ticker, pub + timedelta(days=40), exit_)


# ---------------------------------------------------------------------------
# R1 — author_attribution
# ---------------------------------------------------------------------------

def test_author_attribution_empty_returns_list(tmp_path: Path):
    conn = _conn(tmp_path)
    assert author_attribution(conn) == []


def test_author_attribution_empty_with_meta_explains_why(tmp_path: Path):
    conn = _conn(tmp_path)
    out = author_attribution(conn, include_meta=True)
    assert isinstance(out, dict) and out["rows"] == []
    assert "no manual drops yet" in out["_meta"]["message"]


def test_author_attribution_aggregates_per_author(tmp_path: Path):
    conn = _conn(tmp_path)
    _insert_author(conn, "alice", "Alice")
    _insert_author(conn, "bob", "Bob")
    pub = NOW - timedelta(days=120)

    # Alice: 1 mention of URA → +10%
    _insert_manual_doc(conn, author_id="alice", published_at=pub, text="URA looks great", conviction=4)
    _price_path(conn, "URA", pub, 100.0, 110.0)
    # Bob: 1 mention of SPY → -5%
    _insert_manual_doc(conn, author_id="bob", published_at=pub, text="SPY is rolling over", conviction=3)
    _price_path(conn, "SPY", pub, 400.0, 380.0)
    conn.commit()

    rows = author_attribution(conn, horizons=(30,))
    by = {r["author_id"]: r for r in rows}
    assert by["alice"]["display_name"] == "Alice"
    assert by["alice"]["horizons"][30]["hit_rate"] == pytest.approx(1.0)
    assert by["bob"]["horizons"][30]["hit_rate"] == pytest.approx(0.0)
    # Sort puts Alice first (higher avg forward return)
    assert rows[0]["author_id"] == "alice"


def test_author_attribution_skips_rss_docs_without_author_id(tmp_path: Path):
    """Pivot is on author_id; RSS docs (author_id NULL) must be ignored."""
    conn = _conn(tmp_path)
    pub = NOW - timedelta(days=60)
    # RSS doc — no author_id
    conn.execute(
        """INSERT INTO documents
              (document_id, source_id, title, url, published_at, author,
               content_type, raw_text, cleaned_text, tags_json, ingested_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        ("rss1", "macromicro", "t", None, pub.isoformat(), "MacroMicro",
         "article", "URA bullish", "URA bullish", "[]", pub.isoformat()),
    )
    conn.commit()
    assert author_attribution(conn) == []


# ---------------------------------------------------------------------------
# R2 — conviction_calibration
# ---------------------------------------------------------------------------

def test_conviction_calibration_empty_db(tmp_path: Path):
    conn = _conn(tmp_path)
    out = conviction_calibration(conn)
    assert out["_meta"]["n_signals_total"] == 0
    assert out["horizons"] == {}
    assert "no manual drops" in out["_meta"]["message"]


def test_conviction_calibration_no_conviction_set(tmp_path: Path):
    conn = _conn(tmp_path)
    _insert_author(conn, "alice", "Alice")
    pub = NOW - timedelta(days=60)
    _insert_manual_doc(conn, author_id="alice", published_at=pub, text="URA up", conviction=None)
    conn.commit()
    out = conviction_calibration(conn)
    assert out["_meta"]["n_signals_total"] >= 1
    assert out["_meta"]["n_with_conviction"] == 0
    assert "none carry a user.conviction" in out["_meta"]["message"]


def test_conviction_calibration_buckets_by_level(tmp_path: Path):
    """Conviction 5 → URA → +10%. Conviction 2 → SPY → -5%.
    Monotonic score should be positive (high conviction = better outcome)."""
    conn = _conn(tmp_path)
    _insert_author(conn, "alice", "Alice")
    pub = NOW - timedelta(days=120)

    _insert_manual_doc(conn, author_id="alice", published_at=pub,
                       text="URA conviction max", conviction=5,
                       doc_id="d-conv5")
    _price_path(conn, "URA", pub, 100.0, 110.0)
    _insert_manual_doc(conn, author_id="alice", published_at=pub + timedelta(days=1),
                       text="SPY shrug", conviction=2, doc_id="d-conv2")
    _price_path(conn, "SPY", pub + timedelta(days=1), 400.0, 380.0)
    conn.commit()

    out = conviction_calibration(conn, horizons=(30,))
    by_c = out["horizons"][30]["by_conviction"]
    assert 5 in by_c and 2 in by_c
    assert by_c[5]["hit_rate"] == pytest.approx(1.0)
    assert by_c[2]["hit_rate"] == pytest.approx(0.0)
    # 2 populated buckets → monotonic_score computed
    assert out["horizons"][30]["monotonic_score"] is not None
    # 5 outperforms 2 → positive monotonicity
    assert out["horizons"][30]["monotonic_score"] > 0

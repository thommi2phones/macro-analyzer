"""Tests for echo_ties() in learning/source_attribution.py."""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

import pytest

from macro_positioning.db.schema import initialize_database
from macro_positioning.learning.source_attribution import echo_ties


def _conn(tmp_path: Path) -> sqlite3.Connection:
    db = tmp_path / "echo.db"
    initialize_database(db)
    return sqlite3.connect(db)


def _insert_trade(conn: sqlite3.Connection) -> str:
    """Insert a minimal trade row and return trade_id."""
    trade_id = f"t-{uuid.uuid4().hex[:8]}"
    asset_id = f"a-{uuid.uuid4().hex[:8]}"
    conn.execute(
        "INSERT OR IGNORE INTO assets (asset_id, ticker, asset_name, asset_class) VALUES (?,?,?,?)",
        (asset_id, "TST", "Test", "equity"),
    )
    conn.execute(
        """INSERT INTO trades (trade_id, asset_id, entry_date, entry_price, position_size, stop_loss, status)
           VALUES (?,?,?,?,?,?,?)""",
        (trade_id, asset_id, "2026-05-01T10:00:00", 100.0, 1.0, 95.0, "closed"),
    )
    return trade_id


def _insert_review(conn: sqlite3.Connection, trade_id: str, sources: list[str]) -> None:
    conn.execute(
        """INSERT INTO trade_reviews
               (review_id, trade_id, completed_at, sources_credited_json)
           VALUES (?,?,?,?)""",
        (
            f"r-{uuid.uuid4().hex[:8]}",
            trade_id,
            "2026-05-02T10:00:00",
            json.dumps(sources),
        ),
    )


# ---------------------------------------------------------------------------
# Empty / edge cases
# ---------------------------------------------------------------------------

def test_echo_ties_empty_db_returns_empty(tmp_path: Path):
    conn = _conn(tmp_path)
    assert echo_ties(conn) == []


def test_echo_ties_single_source_no_pairs(tmp_path: Path):
    conn = _conn(tmp_path)
    trade_id = _insert_trade(conn)
    _insert_review(conn, trade_id, ["src_a"])
    conn.commit()
    assert echo_ties(conn) == []


def test_echo_ties_two_sources_in_one_review(tmp_path: Path):
    conn = _conn(tmp_path)
    trade_id = _insert_trade(conn)
    _insert_review(conn, trade_id, ["doomberg", "bianco_research"])
    conn.commit()

    result = echo_ties(conn)
    assert len(result) == 1
    row = result[0]
    assert row["source_a"] == "bianco_research"
    assert row["source_b"] == "doomberg"
    assert row["strength"] == pytest.approx(1.0)


def test_echo_ties_strength_normalized(tmp_path: Path):
    """Pair that appears in 2 reviews has strength 1.0; pair in 1 review gets 0.5."""
    conn = _conn(tmp_path)
    # Pair A-B appears in 2 reviews
    for _ in range(2):
        tid = _insert_trade(conn)
        _insert_review(conn, tid, ["src_a", "src_b"])
    # Pair A-C appears in 1 review
    tid2 = _insert_trade(conn)
    _insert_review(conn, tid2, ["src_a", "src_c"])
    conn.commit()

    result = echo_ties(conn)
    by_pair = {(r["source_a"], r["source_b"]): r for r in result}

    ab = by_pair.get(("src_a", "src_b"))
    assert ab is not None
    assert ab["strength"] == pytest.approx(1.0)

    ac = by_pair.get(("src_a", "src_c"))
    assert ac is not None
    assert ac["strength"] == pytest.approx(0.5)


def test_echo_ties_filters_below_0_1(tmp_path: Path):
    """Pairs with strength < 0.1 are excluded."""
    conn = _conn(tmp_path)
    # Pair A-B appears 9 times → strength 9/9 = 1.0
    for _ in range(9):
        tid = _insert_trade(conn)
        _insert_review(conn, tid, ["src_a", "src_b"])
    # Pair A-C appears once out of 9 → 1/9 ≈ 0.111 → included
    tid = _insert_trade(conn)
    _insert_review(conn, tid, ["src_a", "src_c"])
    conn.commit()

    result = echo_ties(conn)
    strengths = {(r["source_a"], r["source_b"]): r["strength"] for r in result}
    # A-C: 1/9 ≈ 0.11 > 0.1 → included
    assert ("src_a", "src_c") in strengths
    assert strengths[("src_a", "src_c")] >= 0.1


def test_echo_ties_filters_very_weak_pairs(tmp_path: Path):
    """Pairs that are well below 0.1 after normalization are excluded."""
    conn = _conn(tmp_path)
    # Pair A-B appears 100 times → strength 1.0
    for _ in range(100):
        tid = _insert_trade(conn)
        _insert_review(conn, tid, ["src_a", "src_b"])
    # Pair C-D appears once → 1/100 = 0.01 → excluded
    tid = _insert_trade(conn)
    _insert_review(conn, tid, ["src_c", "src_d"])
    conn.commit()

    result = echo_ties(conn)
    pair_keys = {(r["source_a"], r["source_b"]) for r in result}
    assert ("src_a", "src_b") in pair_keys
    assert ("src_c", "src_d") not in pair_keys


def test_echo_ties_sorted_desc_by_strength(tmp_path: Path):
    """Result is sorted by strength descending."""
    conn = _conn(tmp_path)
    # A-B: 3 times
    for _ in range(3):
        tid = _insert_trade(conn)
        _insert_review(conn, tid, ["src_a", "src_b"])
    # A-C: 2 times
    for _ in range(2):
        tid = _insert_trade(conn)
        _insert_review(conn, tid, ["src_a", "src_c"])
    # B-C: 1 time
    tid = _insert_trade(conn)
    _insert_review(conn, tid, ["src_b", "src_c"])
    conn.commit()

    result = echo_ties(conn)
    strengths = [r["strength"] for r in result]
    assert strengths == sorted(strengths, reverse=True)


def test_echo_ties_deduplicates_sources_in_review(tmp_path: Path):
    """Duplicate source IDs within one review should not double-count."""
    conn = _conn(tmp_path)
    tid = _insert_trade(conn)
    # Pass ["src_a", "src_a", "src_b"] — a appears twice but should count once
    _insert_review(conn, tid, ["src_a", "src_a", "src_b"])
    conn.commit()

    result = echo_ties(conn)
    assert len(result) == 1
    assert result[0]["strength"] == pytest.approx(1.0)


def test_echo_ties_invalid_json_rows_skipped(tmp_path: Path):
    """Rows with malformed JSON in sources_credited_json don't crash."""
    conn = _conn(tmp_path)
    tid = _insert_trade(conn)
    conn.execute(
        "INSERT INTO trade_reviews (review_id, trade_id, completed_at, sources_credited_json) VALUES (?,?,?,?)",
        (f"r-{uuid.uuid4().hex[:8]}", tid, "2026-05-02T10:00:00", "not valid json {{"),
    )
    # Also insert a valid one
    _insert_review(conn, tid, ["src_a", "src_b"])
    conn.commit()

    result = echo_ties(conn)
    assert len(result) == 1


def test_echo_ties_return_schema(tmp_path: Path):
    """Each row has exactly source_a, source_b, strength."""
    conn = _conn(tmp_path)
    tid = _insert_trade(conn)
    _insert_review(conn, tid, ["src_x", "src_y"])
    conn.commit()

    result = echo_ties(conn)
    assert len(result) == 1
    row = result[0]
    assert set(row.keys()) == {"source_a", "source_b", "strength"}
    assert isinstance(row["source_a"], str)
    assert isinstance(row["source_b"], str)
    assert isinstance(row["strength"], float)
    assert 0.0 <= row["strength"] <= 1.0

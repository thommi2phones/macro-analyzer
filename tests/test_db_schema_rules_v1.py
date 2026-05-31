"""Schema migration tests for Trading Rule Framework v1.

Verifies:
  - Fresh DB has the new `trades` columns and the new `trade_plans` +
    `portfolio_exposure_snapshots` tables.
  - `initialize_database` is idempotent (run twice, no errors, no
    duplicate columns).
  - An older DB lacking the new columns gets them via the ADD COLUMN
    migration pass.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from macro_positioning.db.schema import initialize_database


_NEW_TRADES_COLUMNS = {
    "setup_category",
    "confluence_score",
    "pattern_subscore",
    "fib_subscore",
    "indicator_subscore",
    "account_risk_pct",
    "correlated_bucket",
    "entry_followed_retest",
    "rule_adherence_score",
}

_NEW_TABLES = {"trade_plans", "portfolio_exposure_snapshots"}


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def test_fresh_db_has_new_trades_columns(tmp_path: Path):
    db = tmp_path / "fresh.db"
    initialize_database(db)
    with sqlite3.connect(db) as conn:
        cols = _table_columns(conn, "trades")
    assert _NEW_TRADES_COLUMNS.issubset(cols), (
        f"missing: {_NEW_TRADES_COLUMNS - cols}"
    )


def test_fresh_db_has_new_tables(tmp_path: Path):
    db = tmp_path / "fresh.db"
    initialize_database(db)
    with sqlite3.connect(db) as conn:
        for t in _NEW_TABLES:
            assert _table_exists(conn, t), f"missing table {t}"


def test_trade_plans_shape(tmp_path: Path):
    db = tmp_path / "fresh.db"
    initialize_database(db)
    with sqlite3.connect(db) as conn:
        cols = _table_columns(conn, "trade_plans")
    expected = {
        "plan_id", "trade_id", "created_at",
        "planned_entry", "planned_stop", "planned_tps_json",
        "planned_size", "planned_account_equity", "planned_risk_pct",
        "planned_setup_category", "planned_confluence_score",
        "planned_pattern_subscore", "planned_fib_subscore",
        "planned_indicator_subscore", "planned_correlated_bucket",
        "planned_entry_strategy", "notes",
    }
    assert expected.issubset(cols), f"missing: {expected - cols}"


def test_trade_plans_enforces_unique_trade_id(tmp_path: Path):
    db = tmp_path / "fresh.db"
    initialize_database(db)
    with sqlite3.connect(db) as conn:
        # Need an asset + trade row to satisfy the FK
        conn.execute(
            "INSERT INTO assets (asset_id, ticker, asset_name, asset_class) "
            "VALUES ('a-1','TST','TST','equity')"
        )
        conn.execute(
            """INSERT INTO trades (
                trade_id, asset_id, entry_date, entry_price, position_size,
                stop_loss, status
            ) VALUES ('trd-1','a-1','2026-05-10T00:00:00Z',100.0,1.0,95.0,'open')"""
        )
        conn.execute(
            """INSERT INTO trade_plans (
                plan_id, trade_id, created_at, planned_entry, planned_stop, planned_size
            ) VALUES ('p-1','trd-1','2026-05-10T00:00:00Z',100,95,1)"""
        )
        conn.commit()

        # Second plan on same trade_id must fail
        import pytest
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO trade_plans (
                    plan_id, trade_id, created_at, planned_entry, planned_stop, planned_size
                ) VALUES ('p-2','trd-1','2026-05-10T00:00:00Z',100,95,1)"""
            )


def test_initialize_is_idempotent(tmp_path: Path):
    db = tmp_path / "idem.db"
    initialize_database(db)
    initialize_database(db)  # second call must not raise
    initialize_database(db)
    with sqlite3.connect(db) as conn:
        cols = _table_columns(conn, "trades")
    # Still a normal single set, not duplicated
    assert _NEW_TRADES_COLUMNS.issubset(cols)


def test_legacy_db_gets_new_columns_via_alter(tmp_path: Path):
    """Simulate an older DB where `trades` predates the new columns.

    We create only the legacy subset of the trades table by hand, then
    run initialize_database — it must ADD COLUMN for each missing v1 field.
    """
    db = tmp_path / "legacy.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            CREATE TABLE trades (
                trade_id TEXT PRIMARY KEY,
                asset_id TEXT NOT NULL,
                entry_date TEXT NOT NULL,
                entry_price REAL NOT NULL,
                position_size REAL NOT NULL,
                stop_loss REAL NOT NULL,
                status TEXT NOT NULL
            )
            """
        )
        conn.commit()
        cols_before = _table_columns(conn, "trades")
    assert _NEW_TRADES_COLUMNS.isdisjoint(cols_before)

    initialize_database(db)

    with sqlite3.connect(db) as conn:
        cols_after = _table_columns(conn, "trades")
    assert _NEW_TRADES_COLUMNS.issubset(cols_after)


def test_legacy_db_gets_new_tables(tmp_path: Path):
    """Older DB without the new tables — they appear after init."""
    db = tmp_path / "legacy2.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE assets (asset_id TEXT PRIMARY KEY, ticker TEXT, "
            "asset_name TEXT, asset_class TEXT)"
        )
        conn.commit()
        for t in _NEW_TABLES:
            assert not _table_exists(conn, t)

    initialize_database(db)

    with sqlite3.connect(db) as conn:
        for t in _NEW_TABLES:
            assert _table_exists(conn, t)

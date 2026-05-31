"""Tests for rules/repository.py — trade_plans CRUD + adherence write."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest

from macro_positioning.db.schema import initialize_database
from macro_positioning.rules import repository as rrepo


def _conn(tmp_path: Path) -> sqlite3.Connection:
    db = tmp_path / "rules_repo.db"
    initialize_database(db)
    return sqlite3.connect(db)


def _seed_trade(conn: sqlite3.Connection, trade_id: str = "trd-1", ticker: str = "TST") -> None:
    aid = f"asset-{uuid.uuid4().hex[:8]}"
    conn.execute(
        "INSERT INTO assets (asset_id, ticker, asset_name, asset_class) VALUES (?,?,?,?)",
        (aid, ticker, ticker, "equity"),
    )
    conn.execute(
        """INSERT INTO trades (
            trade_id, asset_id, entry_date, entry_price, position_size,
            stop_loss, status
        ) VALUES (?,?,?,?,?,?,?)""",
        (trade_id, aid, "2026-05-01T00:00:00Z", 100.0, 1.0, 95.0, "open"),
    )


def _payload(**overrides) -> dict:
    base = {
        "planned_entry": 100.0,
        "planned_stop": 95.0,
        "planned_tps": [110.0, 120.0],
        "planned_size": 1.0,
        "planned_account_equity": 100_000.0,
        "planned_risk_pct": 0.00005,
        "planned_setup_category": "flag",
        "planned_confluence_score": 6,
        "planned_pattern_subscore": 3,
        "planned_fib_subscore": 2,
        "planned_indicator_subscore": 1,
        "planned_correlated_bucket": "uncorrelated",
        "planned_entry_strategy": "breakout_retest",
        "notes": "test",
    }
    base.update(overrides)
    return base


def test_save_plan_roundtrip(tmp_path: Path):
    conn = _conn(tmp_path)
    _seed_trade(conn)
    plan_id = rrepo.save_plan(conn, "trd-1", _payload())
    conn.commit()
    assert plan_id.startswith("plan-")
    fetched = rrepo.get_plan(conn, "trd-1")
    assert fetched is not None
    assert fetched["planned_entry"] == 100.0
    assert fetched["planned_tps"] == [110.0, 120.0]
    assert fetched["planned_setup_category"] == "flag"
    assert fetched["planned_confluence_score"] == 6


def test_get_plan_returns_none_when_absent(tmp_path: Path):
    conn = _conn(tmp_path)
    assert rrepo.get_plan(conn, "missing") is None


def test_save_plan_rejects_unknown_trade(tmp_path: Path):
    conn = _conn(tmp_path)
    with pytest.raises(ValueError):
        rrepo.save_plan(conn, "ghost", _payload())


def test_save_plan_is_append_only(tmp_path: Path):
    conn = _conn(tmp_path)
    _seed_trade(conn)
    rrepo.save_plan(conn, "trd-1", _payload())
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        rrepo.save_plan(conn, "trd-1", _payload(planned_entry=999.0))


def test_hydrate_trade_rule_columns(tmp_path: Path):
    conn = _conn(tmp_path)
    _seed_trade(conn)
    ok = rrepo.hydrate_trade_rule_columns(
        conn,
        "trd-1",
        setup_category="cup",
        confluence_score=7,
        account_risk_pct=0.008,
        correlated_bucket="crypto_l1",
        entry_followed_retest=1,
    )
    conn.commit()
    assert ok is True
    row = conn.execute(
        "SELECT setup_category, confluence_score, account_risk_pct, correlated_bucket, entry_followed_retest "
        "FROM trades WHERE trade_id = 'trd-1'"
    ).fetchone()
    assert row == ("cup", 7, 0.008, "crypto_l1", 1)


def test_hydrate_skips_none_values(tmp_path: Path):
    conn = _conn(tmp_path)
    _seed_trade(conn)
    # First write sets setup_category to flag
    rrepo.hydrate_trade_rule_columns(conn, "trd-1", setup_category="flag")
    # Second call with setup_category=None must not overwrite back to NULL
    rrepo.hydrate_trade_rule_columns(conn, "trd-1", confluence_score=5)
    conn.commit()
    row = conn.execute(
        "SELECT setup_category, confluence_score FROM trades WHERE trade_id = 'trd-1'"
    ).fetchone()
    assert row == ("flag", 5)


def test_hydrate_unknown_trade_returns_false(tmp_path: Path):
    conn = _conn(tmp_path)
    assert rrepo.hydrate_trade_rule_columns(conn, "ghost", confluence_score=7) is False


def test_mark_adherence_clamps_and_persists(tmp_path: Path):
    conn = _conn(tmp_path)
    _seed_trade(conn)
    assert rrepo.mark_adherence(conn, "trd-1", 142) is True  # clamped
    conn.commit()
    val = conn.execute(
        "SELECT rule_adherence_score FROM trades WHERE trade_id = 'trd-1'"
    ).fetchone()[0]
    assert val == 100

    # Negative clamps to 0
    rrepo.mark_adherence(conn, "trd-1", -5)
    val = conn.execute(
        "SELECT rule_adherence_score FROM trades WHERE trade_id = 'trd-1'"
    ).fetchone()[0]
    assert val == 0

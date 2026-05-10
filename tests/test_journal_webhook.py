"""Tests for journal/webhook.py — close-event receiver."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest

from macro_positioning.db.schema import initialize_database
from macro_positioning.journal import webhook as jwebhook


def _conn(tmp_path: Path) -> sqlite3.Connection:
    db = tmp_path / "wh.db"
    initialize_database(db)
    return sqlite3.connect(db)


def _seed_open_trade(conn: sqlite3.Connection, trade_id: str = "trd-1") -> str:
    asset_id = f"asset-{uuid.uuid4().hex[:8]}"
    conn.execute(
        "INSERT INTO assets (asset_id, ticker, asset_name, asset_class) VALUES (?,?,?,?)",
        (asset_id, "TST", "Test", "equity"),
    )
    conn.execute(
        """INSERT INTO trades (
            trade_id, asset_id, entry_date, entry_price, position_size,
            stop_loss, status
        ) VALUES (?,?,?,?,?,?,?)""",
        (trade_id, asset_id, "2026-05-01T00:00:00Z", 100.0, 1.0, 95.0, "open"),
    )
    return trade_id


def test_close_event_flips_status_and_fills_pnl(tmp_path: Path):
    conn = _conn(tmp_path)
    _seed_open_trade(conn, "trd-1")
    result = jwebhook.receive_close_event(
        conn,
        trade_id="trd-1",
        exit_date="2026-05-09T14:30:00Z",
        exit_price=110.5,
        pnl=1050.0,
        pnl_percent=10.5,
        execution_notes="stop hit",
    )
    conn.commit()
    assert result["status"] == "closed"
    assert result["review_status"] == "closed_pending_review"

    row = conn.execute(
        """SELECT status, review_status, exit_date, exit_price, pnl, pnl_percent, execution_notes
           FROM trades WHERE trade_id = 'trd-1'"""
    ).fetchone()
    assert row == ("closed", "closed_pending_review", "2026-05-09T14:30:00Z", 110.5, 1050.0, 10.5, "stop hit")


def test_close_event_idempotent(tmp_path: Path):
    conn = _conn(tmp_path)
    _seed_open_trade(conn, "trd-1")
    jwebhook.receive_close_event(conn, trade_id="trd-1", exit_price=110.0, pnl_percent=10.0)
    conn.commit()
    # Re-fire — should not raise, should still be pending_review
    jwebhook.receive_close_event(conn, trade_id="trd-1", exit_price=111.0, pnl_percent=11.0)
    conn.commit()
    row = conn.execute(
        "SELECT review_status, exit_price, pnl_percent FROM trades WHERE trade_id = 'trd-1'"
    ).fetchone()
    assert row == ("closed_pending_review", 111.0, 11.0)


def test_close_event_unknown_trade_raises(tmp_path: Path):
    conn = _conn(tmp_path)
    with pytest.raises(ValueError):
        jwebhook.receive_close_event(conn, trade_id="missing")

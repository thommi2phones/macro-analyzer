"""Receiver for tactical-executor close events.

The tactical agent POSTs `/api/integration/trade-close` when it closes
a trade; we flip the trade into closed_pending_review and backfill
exit fields. The user then sees the trade pop up in the /journal
pending strip and reviews it through the 7-question modal.
"""

from __future__ import annotations

import sqlite3

from macro_positioning.journal.repository import mark_pending


def receive_close_event(
    conn: sqlite3.Connection,
    *,
    trade_id: str,
    exit_date: str | None = None,
    exit_price: float | None = None,
    pnl: float | None = None,
    pnl_percent: float | None = None,
    execution_notes: str | None = None,
) -> dict:
    """Flip a trade into closed_pending_review and backfill exit fields.

    Idempotent on trade_id. Caller owns commit. Returns
    `{trade_id, review_status, status}`.
    Raises ValueError on unknown trade_id.
    """
    matched = mark_pending(
        conn,
        trade_id,
        exit_date=exit_date,
        exit_price=exit_price,
        pnl=pnl,
        pnl_percent=pnl_percent,
        execution_notes=execution_notes,
    )
    if not matched:
        raise ValueError(f"unknown trade_id: {trade_id!r}")

    row = conn.execute(
        "SELECT status, review_status FROM trades WHERE trade_id = ?",
        (trade_id,),
    ).fetchone()
    return {
        "trade_id": trade_id,
        "status": row[0],
        "review_status": row[1],
    }

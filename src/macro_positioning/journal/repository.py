"""CRUD for trade_reviews + the trades.review_status state machine.

Pure functions over a sqlite3.Connection (matches the `learning/`
package style — keeps SQL in one place and lets tests pass an
in-memory connection without touching SQLiteRepository).

State machine on trades.review_status:
  None  ─(close)→  closed_pending_review  ─(submit review)→  closed_reviewed
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any


PENDING = "closed_pending_review"
REVIEWED = "closed_reviewed"


# ---------------------------------------------------------------------------
# Status flips
# ---------------------------------------------------------------------------


def mark_pending(
    conn: sqlite3.Connection,
    trade_id: str,
    *,
    exit_date: str | None = None,
    exit_price: float | None = None,
    pnl: float | None = None,
    pnl_percent: float | None = None,
    execution_notes: str | None = None,
) -> bool:
    """Flip a trade into closed_pending_review state.

    Idempotent: if already pending or reviewed, leaves status alone but
    still backfills any missing exit_date/pnl fields if provided. Returns
    True if a row matched, False if trade_id is unknown.
    """
    row = conn.execute(
        "SELECT review_status FROM trades WHERE trade_id = ?",
        (trade_id,),
    ).fetchone()
    if row is None:
        return False
    current = row[0]

    sets: list[str] = ["status = 'closed'"]
    params: list[Any] = []
    if current is None:
        sets.append("review_status = ?")
        params.append(PENDING)
    if exit_date is not None:
        sets.append("exit_date = ?")
        params.append(exit_date)
    if exit_price is not None:
        sets.append("exit_price = ?")
        params.append(exit_price)
    if pnl is not None:
        sets.append("pnl = ?")
        params.append(pnl)
    if pnl_percent is not None:
        sets.append("pnl_percent = ?")
        params.append(pnl_percent)
    if execution_notes is not None:
        sets.append("execution_notes = ?")
        params.append(execution_notes)
    params.append(trade_id)

    conn.execute(
        f"UPDATE trades SET {', '.join(sets)} WHERE trade_id = ?",
        params,
    )
    return True


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


_PENDING_SELECT = """
SELECT
    t.trade_id,
    t.asset_id,
    a.ticker,
    t.entry_date,
    t.entry_price,
    t.exit_date,
    t.exit_price,
    t.pnl,
    t.pnl_percent,
    t.position_size,
    t.stop_loss,
    t.target_price,
    t.score_id,
    ts.adjusted_total_score AS score_at_entry,
    ts.regime_id,
    mr.thesis_regime AS regime_at_entry
FROM trades t
LEFT JOIN assets a ON a.asset_id = t.asset_id
LEFT JOIN trade_scores ts ON ts.score_id = t.score_id
LEFT JOIN macro_regimes mr ON mr.regime_id = ts.regime_id
WHERE t.review_status = ?
ORDER BY COALESCE(t.exit_date, t.entry_date) DESC
"""


def list_pending(conn: sqlite3.Connection) -> list[dict]:
    """All trades in closed_pending_review state, with scoring context.

    Each row is the payload the modal needs to render: ticker, entry/exit
    prices+dates, pnl, score-at-entry, regime-at-entry.
    """
    conn.row_factory = sqlite3.Row
    rows = conn.execute(_PENDING_SELECT, (PENDING,)).fetchall()
    return [_pending_row_to_dict(r) for r in rows]


def _pending_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "trade_id": row["trade_id"],
        "asset_id": row["asset_id"],
        "ticker": row["ticker"],
        "entry_date": row["entry_date"],
        "entry_price": row["entry_price"],
        "exit_date": row["exit_date"],
        "exit_price": row["exit_price"],
        "pnl": row["pnl"],
        "pnl_percent": row["pnl_percent"],
        "position_size": row["position_size"],
        "stop_loss": row["stop_loss"],
        "target_price": row["target_price"],
        "score_id": row["score_id"],
        "score_at_entry": row["score_at_entry"],
        "regime_id": row["regime_id"],
        "regime_at_entry": row["regime_at_entry"],
    }


def get_review(conn: sqlite3.Connection, trade_id: str) -> dict | None:
    """Latest review for a trade (None if not yet reviewed).

    JSON columns are parsed into Python objects.
    """
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT *
        FROM trade_reviews
        WHERE trade_id = ?
        ORDER BY completed_at DESC
        LIMIT 1
        """,
        (trade_id,),
    ).fetchone()
    if row is None:
        return None
    return _review_row_to_dict(row)


def _review_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "review_id": row["review_id"],
        "trade_id": row["trade_id"],
        "completed_at": row["completed_at"],
        "thesis_validity": row["thesis_validity"],
        "sources_credited": _parse_json(row["sources_credited_json"], default=[]),
        "execution_scores": _parse_json(row["execution_scores_json"], default={}),
        "setup_score_hindsight": row["setup_score_hindsight"],
        "surprise_factor": _parse_json(row["surprise_factor_json"], default=[]),
        "surprise_note": row["surprise_note"],
        "lesson": row["lesson"],
        "would_retake": row["would_retake"],
        "free_form_notes": row["free_form_notes"],
    }


_RECENT_SELECT = """
SELECT
    r.review_id,
    r.trade_id,
    r.completed_at,
    r.thesis_validity,
    r.sources_credited_json,
    r.execution_scores_json,
    r.setup_score_hindsight,
    r.surprise_factor_json,
    r.surprise_note,
    r.lesson,
    r.would_retake,
    r.free_form_notes,
    a.ticker,
    t.pnl_percent,
    t.entry_date,
    t.exit_date
FROM trade_reviews r
LEFT JOIN trades t ON t.trade_id = r.trade_id
LEFT JOIN assets a ON a.asset_id = t.asset_id
"""


def recent_reviews(
    conn: sqlite3.Connection,
    *,
    limit: int = 20,
    ticker: str | None = None,
    thesis_validity: str | None = None,
) -> list[dict]:
    """Recent reviews for the lessons library, newest first.

    Both filters are optional and combine with AND. `ticker` matches
    case-insensitively; `thesis_validity` is exact.
    """
    conn.row_factory = sqlite3.Row
    where = []
    params: list[Any] = []
    if ticker:
        where.append("UPPER(a.ticker) = UPPER(?)")
        params.append(ticker)
    if thesis_validity:
        where.append("r.thesis_validity = ?")
        params.append(thesis_validity)
    sql = _RECENT_SELECT
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY r.completed_at DESC LIMIT ?"
    params.append(int(limit))
    rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "review_id": r["review_id"],
                "trade_id": r["trade_id"],
                "ticker": r["ticker"],
                "pnl_percent": r["pnl_percent"],
                "entry_date": r["entry_date"],
                "exit_date": r["exit_date"],
                "completed_at": r["completed_at"],
                "thesis_validity": r["thesis_validity"],
                "sources_credited": _parse_json(r["sources_credited_json"], default=[]),
                "execution_scores": _parse_json(r["execution_scores_json"], default={}),
                "setup_score_hindsight": r["setup_score_hindsight"],
                "surprise_factor": _parse_json(r["surprise_factor_json"], default=[]),
                "surprise_note": r["surprise_note"],
                "lesson": r["lesson"],
                "would_retake": r["would_retake"],
                "free_form_notes": r["free_form_notes"],
            }
        )
    return out


# ---------------------------------------------------------------------------
# Insert review (status flip happens in same transaction)
# ---------------------------------------------------------------------------


def insert_review(
    conn: sqlite3.Connection,
    trade_id: str,
    review: dict,
    *,
    completed_at: datetime | None = None,
) -> str:
    """Persist a review and flip review_status='closed_reviewed'.

    Caller owns transaction commit. Returns the new review_id.
    Raises ValueError on unknown trade_id.
    """
    exists = conn.execute(
        "SELECT 1 FROM trades WHERE trade_id = ?",
        (trade_id,),
    ).fetchone()
    if not exists:
        raise ValueError(f"unknown trade_id: {trade_id!r}")

    review_id = f"rev-{uuid.uuid4().hex[:12]}"
    now = (completed_at or datetime.now(timezone.utc)).isoformat()

    conn.execute(
        """
        INSERT INTO trade_reviews (
            review_id, trade_id, completed_at, thesis_validity,
            sources_credited_json, execution_scores_json, setup_score_hindsight,
            surprise_factor_json, surprise_note, lesson, would_retake,
            free_form_notes
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            review_id,
            trade_id,
            now,
            review.get("thesis_validity"),
            json.dumps(review.get("sources_credited") or []),
            json.dumps(review.get("execution_scores") or {}),
            review.get("setup_score_hindsight"),
            json.dumps(review.get("surprise_factor") or []),
            review.get("surprise_note"),
            review.get("lesson"),
            review.get("would_retake"),
            review.get("free_form_notes"),
        ),
    )
    conn.execute(
        "UPDATE trades SET review_status = ? WHERE trade_id = ?",
        (REVIEWED, trade_id),
    )
    return review_id


# ---------------------------------------------------------------------------


def _parse_json(raw: str | None, *, default):
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default

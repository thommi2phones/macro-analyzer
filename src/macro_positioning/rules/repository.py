"""CRUD for trade_plans + the rule columns on trades.

Pure functions over a sqlite3.Connection. Mirrors `journal/repository.py`
so the API/CLI layers stay consistent. Plans are append-only — once
inserted, the UNIQUE(trade_id) constraint blocks any duplicate; this
is the gate against retconning the plan after the trade played out.

Adherence scores are written at review-submit time by
journal.feedback_writer (which calls rules.adherence.compute_adherence).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# trade_plans
# ---------------------------------------------------------------------------


def get_plan(conn: sqlite3.Connection, trade_id: str) -> dict | None:
    """Return the plan row for a trade, or None if none exists.

    JSON columns (planned_tps_json) are parsed into Python lists.
    """
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM trade_plans WHERE trade_id = ? LIMIT 1",
        (trade_id,),
    ).fetchone()
    if row is None:
        return None
    return _plan_row_to_dict(row)


def _plan_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "plan_id": row["plan_id"],
        "trade_id": row["trade_id"],
        "created_at": row["created_at"],
        "planned_entry": row["planned_entry"],
        "planned_stop": row["planned_stop"],
        "planned_tps": _parse_json(row["planned_tps_json"], default=[]),
        "planned_size": row["planned_size"],
        "planned_account_equity": row["planned_account_equity"],
        "planned_risk_pct": row["planned_risk_pct"],
        "planned_setup_category": row["planned_setup_category"],
        "planned_confluence_score": row["planned_confluence_score"],
        "planned_pattern_subscore": row["planned_pattern_subscore"],
        "planned_fib_subscore": row["planned_fib_subscore"],
        "planned_indicator_subscore": row["planned_indicator_subscore"],
        "planned_correlated_bucket": row["planned_correlated_bucket"],
        "planned_entry_strategy": row["planned_entry_strategy"],
        "notes": row["notes"],
    }


def save_plan(
    conn: sqlite3.Connection,
    trade_id: str,
    payload: dict,
    *,
    created_at: datetime | None = None,
) -> str:
    """Persist a new plan. Raises ValueError on unknown trade_id;
    raises sqlite3.IntegrityError if a plan for this trade already exists.

    Caller owns the commit. Returns the new plan_id.
    """
    exists = conn.execute(
        "SELECT 1 FROM trades WHERE trade_id = ?", (trade_id,)
    ).fetchone()
    if not exists:
        raise ValueError(f"unknown trade_id: {trade_id!r}")

    plan_id = f"plan-{uuid.uuid4().hex[:12]}"
    now = (created_at or datetime.now(timezone.utc)).isoformat()

    conn.execute(
        """
        INSERT INTO trade_plans (
            plan_id, trade_id, created_at,
            planned_entry, planned_stop, planned_tps_json,
            planned_size, planned_account_equity, planned_risk_pct,
            planned_setup_category, planned_confluence_score,
            planned_pattern_subscore, planned_fib_subscore,
            planned_indicator_subscore, planned_correlated_bucket,
            planned_entry_strategy, notes
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            plan_id,
            trade_id,
            now,
            payload["planned_entry"],
            payload["planned_stop"],
            json.dumps(payload.get("planned_tps") or []),
            payload["planned_size"],
            payload.get("planned_account_equity"),
            payload.get("planned_risk_pct"),
            payload.get("planned_setup_category"),
            payload.get("planned_confluence_score"),
            payload.get("planned_pattern_subscore"),
            payload.get("planned_fib_subscore"),
            payload.get("planned_indicator_subscore"),
            payload.get("planned_correlated_bucket"),
            payload.get("planned_entry_strategy"),
            payload.get("notes"),
        ),
    )
    return plan_id


def hydrate_trade_rule_columns(
    conn: sqlite3.Connection,
    trade_id: str,
    *,
    setup_category: str | None = None,
    confluence_score: int | None = None,
    pattern_subscore: int | None = None,
    fib_subscore: int | None = None,
    indicator_subscore: int | None = None,
    account_risk_pct: float | None = None,
    correlated_bucket: str | None = None,
    entry_followed_retest: int | None = None,
) -> bool:
    """Write the rule-derived columns onto the trades row at entry time.

    Called once when a plan is saved, so the trade row carries the
    planned-actual baseline for adherence math later. Only updates the
    columns whose new values are not None — None means "leave alone."
    Returns True if a trade matched, False otherwise.
    """
    sets: list[str] = []
    params: list[Any] = []
    for col, val in [
        ("setup_category", setup_category),
        ("confluence_score", confluence_score),
        ("pattern_subscore", pattern_subscore),
        ("fib_subscore", fib_subscore),
        ("indicator_subscore", indicator_subscore),
        ("account_risk_pct", account_risk_pct),
        ("correlated_bucket", correlated_bucket),
        ("entry_followed_retest", entry_followed_retest),
    ]:
        if val is not None:
            sets.append(f"{col} = ?")
            params.append(val)
    if not sets:
        return False
    params.append(trade_id)
    cur = conn.execute(
        f"UPDATE trades SET {', '.join(sets)} WHERE trade_id = ?", params
    )
    return cur.rowcount > 0


def mark_adherence(
    conn: sqlite3.Connection, trade_id: str, score: int
) -> bool:
    """Write the final rule_adherence_score (0..100) onto a trade.

    Called by journal.feedback_writer at review-submit time. Idempotent —
    rewrites the column with the latest value.
    """
    score = max(0, min(100, int(score)))
    cur = conn.execute(
        "UPDATE trades SET rule_adherence_score = ? WHERE trade_id = ?",
        (score, trade_id),
    )
    return cur.rowcount > 0


def _parse_json(raw: str | None, *, default):
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default

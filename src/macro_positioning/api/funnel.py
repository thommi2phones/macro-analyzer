"""Funnel spine endpoints — concepts (step ②) and plans (step ③).

The funnel goes watchlist → concept → plan → trade → review. This
router owns the middle two stages. Concepts are marked watchlist
items the operator wants to track; plans are the actionable
entry/stop/target packages that get activated into live trades.

Mounted at /api/funnel/* by api/main.py. Mock data in web/data.mock.js
mirrors these shapes for offline rendering when the DB is empty.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from macro_positioning.core.settings import settings


router = APIRouter(prefix="/api/funnel", tags=["funnel"])


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.sqlite_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_concept(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "concept_id": row["concept_id"],
        "asset_id": row["asset_id"],
        "source": row["source"],
        "status": row["status"],
        "suggested_by_system": bool(row["suggested_by_system"]),
        "suggestion_reason": row["suggestion_reason"],
        "score_at_mark": row["score_at_mark"],
        "tier_at_mark": row["tier_at_mark"],
        "side_at_mark": row["side_at_mark"],
        "thesis_text": row["thesis_text"],
        "trade_plan_id": row["trade_plan_id"],
        "marked_at": row["marked_at"],
        "promoted_at": row["promoted_at"],
        "retired_at": row["retired_at"],
        "retire_reason": row["retire_reason"],
        "updated_at": row["updated_at"],
    }


def _row_to_plan(row: sqlite3.Row) -> dict[str, Any]:
    targets = []
    if row["targets_json"]:
        try:
            targets = json.loads(row["targets_json"])
        except (TypeError, ValueError):
            targets = []
    return {
        "plan_id": row["plan_id"],
        "concept_id": row["concept_id"],
        "asset_id": row["asset_id"],
        "side": row["side"],
        "entry": row["entry"],
        "stop": row["stop"],
        "targets": targets,
        "size_usd": row["size_usd"],
        "size_r": row["size_r"],
        "time_horizon": row["time_horizon"],
        "thesis": row["thesis"],
        "invalidation": row["invalidation"],
        "gate_status": row["gate_status"],
        "status": row["status"],
        "trade_id": row["trade_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "activated_at": row["activated_at"],
        "cancelled_at": row["cancelled_at"],
    }


# ── Concepts ──────────────────────────────────────────────────────────────


class ConceptMarkPayload(BaseModel):
    asset_id: str
    source: str = Field(default="watchlist_manual")
    thesis_text: Optional[str] = None
    score_at_mark: Optional[float] = None
    tier_at_mark: Optional[str] = None
    side_at_mark: Optional[str] = None
    suggested_by_system: bool = False
    suggestion_reason: Optional[str] = None


class ConceptPatchPayload(BaseModel):
    thesis_text: Optional[str] = None
    status: Optional[str] = None
    retire_reason: Optional[str] = None


@router.get("/concepts")
def list_concepts(status: Optional[str] = None) -> dict[str, Any]:
    with _connect() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM trade_concepts WHERE status = ? "
                "ORDER BY marked_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trade_concepts ORDER BY marked_at DESC"
            ).fetchall()
    return {"concepts": [_row_to_concept(r) for r in rows]}


@router.post("/concepts")
def mark_concept(payload: ConceptMarkPayload) -> dict[str, Any]:
    cid = f"concept-{uuid.uuid4().hex[:10]}"
    now = _now()
    with _connect() as conn:
        # Bounce repeated marks for the same active asset back as the
        # existing concept rather than creating a duplicate row.
        existing = conn.execute(
            "SELECT * FROM trade_concepts WHERE asset_id = ? AND status = 'active'",
            (payload.asset_id,),
        ).fetchone()
        if existing:
            return {"concept": _row_to_concept(existing), "deduped": True}
        conn.execute(
            """
            INSERT INTO trade_concepts (
                concept_id, asset_id, source, status,
                suggested_by_system, suggestion_reason,
                score_at_mark, tier_at_mark, side_at_mark,
                thesis_text, marked_at, updated_at
            ) VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cid, payload.asset_id, payload.source,
                1 if payload.suggested_by_system else 0,
                payload.suggestion_reason,
                payload.score_at_mark, payload.tier_at_mark,
                payload.side_at_mark, payload.thesis_text,
                now, now,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM trade_concepts WHERE concept_id = ?", (cid,)
        ).fetchone()
    return {"concept": _row_to_concept(row), "deduped": False}


@router.patch("/concepts/{concept_id}")
def patch_concept(concept_id: str, payload: ConceptPatchPayload) -> dict[str, Any]:
    now = _now()
    with _connect() as conn:
        existing = conn.execute(
            "SELECT * FROM trade_concepts WHERE concept_id = ?", (concept_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(404, "concept not found")
        sets, args = [], []
        if payload.thesis_text is not None:
            sets.append("thesis_text = ?")
            args.append(payload.thesis_text)
        if payload.status:
            sets.append("status = ?")
            args.append(payload.status)
            if payload.status == "retired":
                sets.append("retired_at = ?")
                args.append(now)
            if payload.status == "promoted":
                sets.append("promoted_at = ?")
                args.append(now)
        if payload.retire_reason is not None:
            sets.append("retire_reason = ?")
            args.append(payload.retire_reason)
        sets.append("updated_at = ?")
        args.append(now)
        args.append(concept_id)
        conn.execute(
            f"UPDATE trade_concepts SET {', '.join(sets)} WHERE concept_id = ?",
            args,
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM trade_concepts WHERE concept_id = ?", (concept_id,)
        ).fetchone()
    return {"concept": _row_to_concept(row)}


@router.get("/concepts/suggestions")
def concept_suggestions() -> dict[str, Any]:
    """System-proposed concepts: high-score watchlist rows not yet marked.

    Pulls the latest trade_score per asset, filters to score ≥ 70,
    excludes assets already in an active concept row. Empty when no
    scores exist — the SPA falls back to data.mock.js suggestions
    for the offline-render case.
    """
    with _connect() as conn:
        rows = conn.execute(
            """
            WITH latest_scores AS (
                SELECT ts.*, ROW_NUMBER() OVER (
                    PARTITION BY t.asset_id
                    ORDER BY ts.scored_at DESC
                ) AS rn,
                a.asset_id AS a_id, a.ticker
                FROM trade_scores ts
                JOIN technical_setups t ON ts.setup_id = t.setup_id
                JOIN assets a ON t.asset_id = a.asset_id
            )
            SELECT * FROM latest_scores
            WHERE rn = 1
              AND adjusted_total_score >= 70
              AND a_id NOT IN (
                  SELECT asset_id FROM trade_concepts WHERE status = 'active'
              )
            ORDER BY adjusted_total_score DESC
            LIMIT 25
            """
        ).fetchall()
    suggestions = []
    for r in rows:
        suggestions.append({
            "asset_id": r["a_id"],
            "ticker": r["ticker"],
            "score": r["adjusted_total_score"],
            "tier": r["position_size_tier"],
            "reason": (
                f"score {r['adjusted_total_score']} · grade {r['grade']} · "
                f"latest setup"
            ),
        })
    return {"suggestions": suggestions}


# ── Plans ─────────────────────────────────────────────────────────────────


class PlanCreatePayload(BaseModel):
    asset_id: str
    side: str
    concept_id: Optional[str] = None
    entry: Optional[float] = None
    stop: Optional[float] = None
    targets: list[dict[str, Any]] = Field(default_factory=list)
    size_usd: Optional[float] = None
    size_r: Optional[float] = None
    time_horizon: Optional[str] = None
    thesis: Optional[str] = None
    invalidation: Optional[str] = None


class PlanPatchPayload(BaseModel):
    entry: Optional[float] = None
    stop: Optional[float] = None
    targets: Optional[list[dict[str, Any]]] = None
    size_usd: Optional[float] = None
    size_r: Optional[float] = None
    time_horizon: Optional[str] = None
    thesis: Optional[str] = None
    invalidation: Optional[str] = None
    status: Optional[str] = None
    gate_status: Optional[str] = None


@router.get("/plans")
def list_plans(status: Optional[str] = None) -> dict[str, Any]:
    with _connect() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM trade_plans WHERE status = ? "
                "ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trade_plans ORDER BY created_at DESC"
            ).fetchall()
    return {"plans": [_row_to_plan(r) for r in rows]}


@router.post("/plans")
def create_plan(payload: PlanCreatePayload) -> dict[str, Any]:
    pid = f"plan-{uuid.uuid4().hex[:10]}"
    now = _now()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO trade_plans (
                plan_id, concept_id, asset_id, side,
                entry, stop, targets_json,
                size_usd, size_r, time_horizon,
                thesis, invalidation,
                gate_status, status,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unchecked', 'draft', ?, ?)
            """,
            (
                pid, payload.concept_id, payload.asset_id, payload.side,
                payload.entry, payload.stop, json.dumps(payload.targets),
                payload.size_usd, payload.size_r, payload.time_horizon,
                payload.thesis, payload.invalidation,
                now, now,
            ),
        )
        if payload.concept_id:
            conn.execute(
                """
                UPDATE trade_concepts
                SET status='promoted', promoted_at=?, trade_plan_id=?, updated_at=?
                WHERE concept_id=?
                """,
                (now, pid, now, payload.concept_id),
            )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM trade_plans WHERE plan_id = ?", (pid,)
        ).fetchone()
    return {"plan": _row_to_plan(row)}


@router.patch("/plans/{plan_id}")
def patch_plan(plan_id: str, payload: PlanPatchPayload) -> dict[str, Any]:
    now = _now()
    with _connect() as conn:
        existing = conn.execute(
            "SELECT * FROM trade_plans WHERE plan_id = ?", (plan_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(404, "plan not found")
        sets, args = [], []
        for col in ("entry", "stop", "size_usd", "size_r",
                    "time_horizon", "thesis", "invalidation",
                    "status", "gate_status"):
            val = getattr(payload, col)
            if val is not None:
                sets.append(f"{col} = ?")
                args.append(val)
        if payload.targets is not None:
            sets.append("targets_json = ?")
            args.append(json.dumps(payload.targets))
        if payload.status == "cancelled":
            sets.append("cancelled_at = ?")
            args.append(now)
        sets.append("updated_at = ?")
        args.append(now)
        args.append(plan_id)
        conn.execute(
            f"UPDATE trade_plans SET {', '.join(sets)} WHERE plan_id = ?",
            args,
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM trade_plans WHERE plan_id = ?", (plan_id,)
        ).fetchone()
    return {"plan": _row_to_plan(row)}


@router.post("/plans/{plan_id}/activate")
def activate_plan(plan_id: str) -> dict[str, Any]:
    """Mark a plan live and create the backing trades row.

    The trade carries plan_id so journal step-5 analytics can walk
    concept → plan → trade lineage.
    """
    now = _now()
    tid = f"trade-{uuid.uuid4().hex[:10]}"
    with _connect() as conn:
        plan = conn.execute(
            "SELECT * FROM trade_plans WHERE plan_id = ?", (plan_id,)
        ).fetchone()
        if not plan:
            raise HTTPException(404, "plan not found")
        if plan["status"] != "draft":
            raise HTTPException(409, f"plan status is {plan['status']}, not draft")
        if plan["entry"] is None or plan["stop"] is None:
            raise HTTPException(422, "plan needs entry and stop before activation")
        target_price = None
        if plan["targets_json"]:
            try:
                tgts = json.loads(plan["targets_json"])
                if tgts:
                    target_price = tgts[0].get("price")
            except (TypeError, ValueError):
                pass
        conn.execute(
            """
            INSERT INTO trades (
                trade_id, asset_id, entry_date, entry_price,
                position_size, stop_loss, target_price,
                status, plan_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)
            """,
            (
                tid, plan["asset_id"], now, plan["entry"],
                plan["size_usd"] or 0.0, plan["stop"], target_price,
                plan_id,
            ),
        )
        conn.execute(
            """
            UPDATE trade_plans
            SET status='live', trade_id=?, activated_at=?, updated_at=?
            WHERE plan_id=?
            """,
            (tid, now, now, plan_id),
        )
        conn.commit()
        plan_row = conn.execute(
            "SELECT * FROM trade_plans WHERE plan_id = ?", (plan_id,)
        ).fetchone()
    return {"plan": _row_to_plan(plan_row), "trade_id": tid}

"""Dashboard data for the Brain Activity + Reasoning Trail panels.

Exposes JSON endpoints that Stream C's frontend will consume:
  GET /api/dashboard/brain/activity     — last N brain calls
  GET /api/dashboard/brain/stats        — aggregate stats
  GET /api/dashboard/brain/reasoning    — latest thesis with evidence chain
  GET /api/dashboard/sources            — source weights table
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from macro_positioning.brain.observability import (
    BrainCallRecord,
    call_stats,
    recent_calls,
)
from macro_positioning.core.settings import settings
from macro_positioning.db.repository import SQLiteRepository
from macro_positioning.integration import source_weights as sw_module
from macro_positioning.integration.source_weights import SourceWeight

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


# ---------------------------------------------------------------------------
# Brain activity
# ---------------------------------------------------------------------------

class BrainActivityResponse(BaseModel):
    stats: dict
    recent: list[BrainCallRecord]


@router.get("/brain/activity", response_model=BrainActivityResponse)
def brain_activity(limit: int = Query(20, ge=1, le=200)) -> BrainActivityResponse:
    return BrainActivityResponse(
        stats=call_stats(),
        recent=recent_calls(limit=limit),
    )


@router.get("/brain/stats")
def brain_stats() -> dict:
    return call_stats()


# ---------------------------------------------------------------------------
# Reasoning trail — latest thesis with evidence
# ---------------------------------------------------------------------------

class ReasoningNode(BaseModel):
    thesis_id: str
    thesis: str
    theme: str
    direction: str
    confidence: float
    evidence_count: int
    source_ids: list[str]
    sources_with_weights: list[dict]  # [{source_id, weight}]


@router.get("/brain/reasoning")
def brain_reasoning(limit: int = Query(10, ge=1, le=50)) -> list[ReasoningNode]:
    """Return the latest theses with their source chain + source weights."""
    repo = SQLiteRepository(settings.sqlite_path)
    theses = repo.list_theses()[:limit]

    out = []
    for t in theses:
        sources_with_weights = []
        for sid in t.source_ids:
            w = sw_module.get_weight(sid)
            sources_with_weights.append({
                "source_id": sid,
                "weight": round(w.weight, 3),
                "wins": w.wins,
                "losses": w.losses,
            })

        out.append(ReasoningNode(
            thesis_id=t.thesis_id,
            thesis=t.thesis,
            theme=t.theme,
            direction=t.direction.value,
            confidence=t.confidence,
            evidence_count=len(t.evidence),
            source_ids=t.source_ids,
            sources_with_weights=sources_with_weights,
        ))
    return out


# ---------------------------------------------------------------------------
# Source weights panel
# ---------------------------------------------------------------------------

class SourcesResponse(BaseModel):
    stats: dict
    sources: list[SourceWeight]


@router.get("/sources", response_model=SourcesResponse)
def source_weights_panel() -> SourcesResponse:
    return SourcesResponse(
        stats=sw_module.stats(),
        sources=sw_module.list_weights(),
    )

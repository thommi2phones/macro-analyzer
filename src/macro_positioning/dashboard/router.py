"""FastAPI router for dashboard endpoints.

Serves:
  - JSON data APIs at /api/dashboard/*
  - Interactive checklist PATCH at /api/checklist/{id}
  - Unified HTML dashboard at /dashboard
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from macro_positioning.dashboard.brain_panel import router as brain_panel_router
from macro_positioning.dashboard.checklist import (
    Checklist,
    ChecklistItem,
    load_checklist,
    toggle_item,
)
from macro_positioning.dashboard.command_data import CommandCenterSnapshot, build_command_snapshot
from macro_positioning.dashboard.ops_data import OpsSnapshot, build_ops_snapshot
from macro_positioning.dashboard.templates import command_center_html, ops_dashboard_html

router = APIRouter()
router.include_router(brain_panel_router)


# ---------------------------------------------------------------------------
# JSON data APIs
# ---------------------------------------------------------------------------

@router.get("/api/dashboard/ops", response_model=OpsSnapshot)
def ops_data() -> OpsSnapshot:
    return build_ops_snapshot()


@router.get("/api/dashboard/command-center", response_model=CommandCenterSnapshot)
def command_center_data() -> CommandCenterSnapshot:
    return build_command_snapshot()


@router.get("/api/checklist", response_model=Checklist)
def get_checklist() -> Checklist:
    return load_checklist()


@router.patch("/api/checklist/{item_id}")
def patch_checklist_item(item_id: str, status: str | None = None) -> JSONResponse:
    """Toggle a checklist item. Optional ?status=done|todo|in_progress query param."""
    item = toggle_item(item_id, new_status=status)
    if item is None:
        return JSONResponse(status_code=404, content={"error": f"Item '{item_id}' not found"})
    return JSONResponse(content=item.model_dump())


# ---------------------------------------------------------------------------
# HTML dashboards
# ---------------------------------------------------------------------------

@router.get("/dashboard/ops", response_class=HTMLResponse)
def ops_dashboard() -> HTMLResponse:
    return HTMLResponse(content=ops_dashboard_html())


@router.get("/dashboard/command-center", response_class=HTMLResponse)
def command_center_dashboard() -> HTMLResponse:
    return HTMLResponse(content=command_center_html())


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_redirect() -> HTMLResponse:
    return HTMLResponse(
        content='<html><head><meta http-equiv="refresh" content="0;url=/dashboard/ops"></head></html>'
    )

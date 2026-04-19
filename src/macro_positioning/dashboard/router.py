"""FastAPI router for dashboard endpoints.

Two primary dashboards:
  - `/positioning` — trader-facing consumer UI (output view)
  - `/dev` — builder-facing status UI (project/ops view)

Root `/` redirects to `/positioning`. JSON APIs at `/api/dashboard/*`.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from macro_positioning.dashboard.brain_panel import router as brain_panel_router
from macro_positioning.dashboard.checklist import (
    Checklist,
    ChecklistItem,
    load_checklist,
    toggle_item,
)
from macro_positioning.dashboard.command_data import CommandCenterSnapshot, build_command_snapshot
from macro_positioning.dashboard.dev_ui import dev_dashboard_html
from macro_positioning.dashboard.ops_data import OpsSnapshot, build_ops_snapshot
from macro_positioning.dashboard.output_ui import positioning_dashboard_html

router = APIRouter()
router.include_router(brain_panel_router)


# ---- JSON data APIs --------------------------------------------------------

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
    item = toggle_item(item_id, new_status=status)
    if item is None:
        return JSONResponse(status_code=404, content={"error": f"Item '{item_id}' not found"})
    return JSONResponse(content=item.model_dump())


# ---- HTML dashboards -------------------------------------------------------

@router.get("/positioning", response_class=HTMLResponse)
def positioning_dashboard() -> HTMLResponse:
    """Trader-facing output UI — the product."""
    return HTMLResponse(content=positioning_dashboard_html())


@router.get("/dev", response_class=HTMLResponse)
def dev_dashboard() -> HTMLResponse:
    """Builder-facing status UI — checklist, brain activity, system health."""
    return HTMLResponse(content=dev_dashboard_html())


@router.get("/")
def root_redirect() -> RedirectResponse:
    return RedirectResponse(url="/positioning", status_code=307)


# ---- Legacy redirects (keep old URLs working) ------------------------------

@router.get("/dashboard")
def dashboard_redirect() -> RedirectResponse:
    return RedirectResponse(url="/positioning", status_code=307)


@router.get("/dashboard/ops")
def legacy_ops() -> RedirectResponse:
    return RedirectResponse(url="/dev", status_code=307)


@router.get("/dashboard/command-center")
def legacy_command_center() -> RedirectResponse:
    return RedirectResponse(url="/positioning", status_code=307)

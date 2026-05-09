"""FastAPI router for dashboard JSON APIs + legacy HTML route redirects.

The old per-view HTML pages (positioning, dev, tactical, terminal,
guide) have been replaced by the single SPA at /web/index.html
(Claude Design output). This router still exposes the JSON APIs the
old dashboards used; those data feeds back the new SPA via
`dashboard/desk_routes.py` and remain useful for programmatic access.

Old route → new behavior:
  /                  → 307 → /web/index.html
  /terminal          → 307 → /web/index.html
  /positioning       → 307 → /web/index.html
  /tactical          → 307 → /web/index.html
  /dev               → 307 → /web/index.html
  /guide             → 307 → /web/index.html
  /dashboard         → 307 → /web/index.html (legacy)
  /dashboard/ops     → 307 → /web/index.html (legacy)
  /dashboard/command-center → 307 → /web/index.html (legacy)

JSON APIs preserved (used by the SPA + external):
  /api/dashboard/ops
  /api/dashboard/command-center
  /api/dashboard/tactical-state
  /api/dashboard/mgmt
  /api/checklist  + PATCH
  /api/dashboard/brain/*  (registered by brain_panel sub-router)
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse, RedirectResponse

from macro_positioning.dashboard.brain_panel import router as brain_panel_router
from macro_positioning.dashboard.checklist import (
    Checklist,
    ChecklistItem,
    load_checklist,
    toggle_item,
)
from macro_positioning.dashboard.command_data import CommandCenterSnapshot, build_command_snapshot
from macro_positioning.dashboard.mgmt_data import MgmtSnapshot, build_mgmt_snapshot
from macro_positioning.dashboard.ops_data import OpsSnapshot, build_ops_snapshot
from macro_positioning.integration import tactical_client


router = APIRouter()
router.include_router(brain_panel_router)


# ---- JSON data APIs (preserved) -------------------------------------------

@router.get("/api/dashboard/ops", response_model=OpsSnapshot)
def ops_data() -> OpsSnapshot:
    return build_ops_snapshot()


@router.get("/api/dashboard/command-center", response_model=CommandCenterSnapshot)
def command_center_data() -> CommandCenterSnapshot:
    return build_command_snapshot()


@router.get("/api/dashboard/tactical-state")
def tactical_state() -> dict:
    return tactical_client.fetch_tactical_snapshot()


@router.get("/api/dashboard/mgmt", response_model=MgmtSnapshot)
def mgmt_data(decisions_limit: int = 8, commits_limit: int = 10) -> MgmtSnapshot:
    return build_mgmt_snapshot(
        decisions_limit=decisions_limit,
        commits_limit=commits_limit,
    )


@router.get("/api/checklist", response_model=Checklist)
def get_checklist() -> Checklist:
    return load_checklist()


@router.patch("/api/checklist/{item_id}")
def patch_checklist_item(item_id: str, status: str | None = None) -> JSONResponse:
    item = toggle_item(item_id, new_status=status)
    if item is None:
        return JSONResponse(status_code=404, content={"error": f"Item '{item_id}' not found"})
    return JSONResponse(content=item.model_dump())


# ---- Legacy HTML route redirects ------------------------------------------
# Every old per-view URL now lands on the SPA. The SPA's internal tab
# state determines what shows; deep-linking to a specific view via URL
# can be added later via hash routing in the SPA.

_SPA = "/web/index.html"


@router.get("/")
def root_redirect() -> RedirectResponse:
    return RedirectResponse(url=_SPA, status_code=307)


@router.get("/terminal")
def legacy_terminal() -> RedirectResponse:
    return RedirectResponse(url=_SPA, status_code=307)


@router.get("/positioning")
def legacy_positioning() -> RedirectResponse:
    return RedirectResponse(url=_SPA, status_code=307)


@router.get("/tactical")
def legacy_tactical() -> RedirectResponse:
    return RedirectResponse(url=_SPA, status_code=307)


@router.get("/dev")
def legacy_dev() -> RedirectResponse:
    return RedirectResponse(url=_SPA, status_code=307)


@router.get("/guide")
def legacy_guide() -> RedirectResponse:
    return RedirectResponse(url=_SPA, status_code=307)


@router.get("/dashboard")
def legacy_dashboard() -> RedirectResponse:
    return RedirectResponse(url=_SPA, status_code=307)


@router.get("/dashboard/ops")
def legacy_dashboard_ops() -> RedirectResponse:
    return RedirectResponse(url=_SPA, status_code=307)


@router.get("/dashboard/command-center")
def legacy_dashboard_cc() -> RedirectResponse:
    return RedirectResponse(url=_SPA, status_code=307)

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from macro_positioning.core.models import PipelineRunRequest, PipelineRunResult, PositioningMemo, SourceOnboardingRequest, Thesis
from macro_positioning.core.settings import settings
from macro_positioning.dashboard.desk_routes import router as desk_router
from macro_positioning.dashboard.router import router as dashboard_router
from macro_positioning.integration.endpoints import router as integration_router
from macro_positioning.db.repository import SQLiteRepository
from macro_positioning.db.schema import initialize_database
from macro_positioning.ingestion.source_registry import load_source_registry
from macro_positioning.pipelines.run_pipeline import build_pipeline
from macro_positioning.services.framework import default_credential_requirements, onboarding_template

app = FastAPI(title="Macro Positioning Analyzer", version="0.1.0")


# ---------------------------------------------------------------------------
# Bearer auth — only enforced when MPA_AUTH_TOKEN is set (i.e. on deployed
# instances). Local dev leaves the env var unset and the middleware no-ops.
# Static SPA assets and the health endpoint stay public so the browser can
# fetch index.html and the API can be probed by Render's health check.
# ---------------------------------------------------------------------------

_PUBLIC_PREFIXES = ("/web/", "/health", "/login")


@app.middleware("http")
async def _bearer_auth(request: Request, call_next):
    token = settings.auth_token
    if not token:
        return await call_next(request)

    path = request.url.path
    if path == "/" or any(path.startswith(p) for p in _PUBLIC_PREFIXES):
        return await call_next(request)

    header = request.headers.get("authorization", "")
    cookie = request.cookies.get("mpa_token", "")
    expected = f"Bearer {token}"
    if header != expected and cookie != token:
        return JSONResponse(
            {"detail": "unauthorized"},
            status_code=401,
        )
    return await call_next(request)

# Desk routes (dynamic /web/data.js + /api/desk/data) MUST register
# BEFORE the StaticFiles mount so they take precedence over the static
# data.mock.js fallback.
app.include_router(desk_router)
app.include_router(dashboard_router)
app.include_router(integration_router)

initialize_database(settings.sqlite_path)
repository = SQLiteRepository(settings.sqlite_path)


# ---------------------------------------------------------------------------
# Static SPA mount (Claude Design output)
# ---------------------------------------------------------------------------
# Serves web/index.html, *.jsx, styles.css, etc. Dynamic /web/data.js is
# handled by desk_router above and shadows the static fallback at
# web/data.mock.js. SPA reads `window.MA_DATA` on first paint.
_WEB_DIR = settings.base_dir / "web"
if _WEB_DIR.is_dir():
    app.mount("/web", StaticFiles(directory=_WEB_DIR, html=True), name="web")


# Convenience root → SPA. Old per-view routes (/positioning, /dev, etc)
# are 307-redirected here too via dashboard/router.py.
@app.get("/desk")
def desk_root_redirect() -> RedirectResponse:
    return RedirectResponse(url="/web/index.html", status_code=307)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/pipeline/run", response_model=PipelineRunResult)
def run_pipeline(request: PipelineRunRequest) -> PipelineRunResult:
    pipeline = build_pipeline()
    return pipeline.run(request.documents, context=request.context)


@app.get("/theses", response_model=list[Thesis])
def list_theses() -> list[Thesis]:
    return repository.list_theses()


@app.get("/memos/latest", response_model=PositioningMemo)
def latest_memo() -> PositioningMemo:
    memo = repository.latest_memo()
    if memo is None:
        raise HTTPException(status_code=404, detail="No memo has been generated yet.")
    return memo


@app.get("/framework/credentials")
def framework_credentials() -> list[dict]:
    return [item.model_dump() for item in default_credential_requirements()]


@app.get("/framework/onboarding-template", response_model=list[SourceOnboardingRequest])
def framework_onboarding_template() -> list[SourceOnboardingRequest]:
    return onboarding_template()


@app.get("/sources/example")
def example_sources() -> list[dict]:
    path = Path("config/sources.example.json")
    return [item.model_dump() for item in load_source_registry(path)]


# ---------------------------------------------------------------------------
# Chart analysis
# ---------------------------------------------------------------------------

class ChartAnalysisRequest(BaseModel):
    image_url: str
    asset_context: str = ""
    additional_context: str = ""


class BatchChartRequest(BaseModel):
    charts: list[dict] = Field(..., description="List of {url, asset_context} dicts")


@app.post("/charts/analyze")
def analyze_chart(request: ChartAnalysisRequest) -> dict:
    from macro_positioning.brain import build_brain_client
    brain = build_brain_client()
    try:
        return brain.analyze_chart(
            image_url=request.image_url,
            asset_context=request.asset_context,
            additional_context=request.additional_context,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/charts/analyze/batch")
def analyze_charts_batch(request: BatchChartRequest) -> list[dict]:
    from macro_positioning.brain.vision import analyze_multiple_charts
    try:
        return analyze_multiple_charts(request.charts)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from macro_positioning.core.models import PipelineRunRequest, PipelineRunResult, PositioningMemo, SourceOnboardingRequest, Thesis
from macro_positioning.core.settings import settings
from macro_positioning.dashboard.router import router as dashboard_router
from macro_positioning.db.repository import SQLiteRepository
from macro_positioning.db.schema import initialize_database
from macro_positioning.ingestion.source_registry import load_source_registry
from macro_positioning.pipelines.run_pipeline import build_pipeline
from macro_positioning.services.framework import default_credential_requirements, onboarding_template

app = FastAPI(title="Macro Positioning Analyzer", version="0.1.0")
app.include_router(dashboard_router)

initialize_database(settings.sqlite_path)
repository = SQLiteRepository(settings.sqlite_path)


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
    from macro_positioning.llm.chart_analyzer import analyze_chart_url
    try:
        return analyze_chart_url(
            image_url=request.image_url,
            asset_context=request.asset_context,
            additional_context=request.additional_context,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/charts/analyze/batch")
def analyze_charts_batch(request: BatchChartRequest) -> list[dict]:
    from macro_positioning.llm.chart_analyzer import analyze_multiple_charts
    try:
        return analyze_multiple_charts(request.charts)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

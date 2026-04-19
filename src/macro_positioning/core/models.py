from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class SourceType(str, Enum):
    newsletter = "newsletter"
    website = "website"
    podcast = "podcast"
    social = "social"
    video = "video"
    report = "report"
    manual = "manual"


class SourcePriority(str, Enum):
    core = "core"
    secondary = "secondary"
    experimental = "experimental"


class ViewDirection(str, Enum):
    bullish = "bullish"
    bearish = "bearish"
    neutral = "neutral"
    mixed = "mixed"
    watchful = "watchful"


class ThesisStatus(str, Enum):
    active = "active"
    weakening = "weakening"
    invalidated = "invalidated"
    archived = "archived"


class SourceDefinition(BaseModel):
    source_id: str
    name: str
    source_type: SourceType
    author: str | None = None
    priority: SourcePriority = SourcePriority.secondary
    trust_weight: float = Field(default=0.5, ge=0.0, le=1.0)
    market_focus: list[str] = Field(default_factory=list)
    access_notes: str | None = None
    default_url: str | None = None
    channels: list["SourceChannel"] = Field(default_factory=list)
    research_style: str | None = None
    validation_focus: list[str] = Field(default_factory=list)


class SourceChannel(BaseModel):
    channel_type: Literal["rss", "website", "x", "substack", "podcast", "youtube", "telegram", "pdf", "manual"]
    label: str
    url: str
    notes: str | None = None
    active: bool = True


class CredentialRequirement(BaseModel):
    key: str
    label: str
    required_for: list[str] = Field(default_factory=list)
    description: str
    optional: bool = False


class SourceOnboardingRequest(BaseModel):
    source: SourceDefinition
    rationale: str | None = None
    required_credentials: list[CredentialRequirement] = Field(default_factory=list)
    implementation_notes: list[str] = Field(default_factory=list)


class RawDocument(BaseModel):
    source_id: str
    title: str
    url: str | None = None
    published_at: datetime = Field(default_factory=utc_now)
    author: str | None = None
    content_type: Literal["article", "post", "transcript", "report", "note"] = "article"
    raw_text: str
    tags: list[str] = Field(default_factory=list)


class NormalizedDocument(BaseModel):
    document_id: str
    source_id: str
    title: str
    url: str | None = None
    published_at: datetime
    author: str | None = None
    content_type: str
    raw_text: str
    cleaned_text: str
    tags: list[str] = Field(default_factory=list)
    ingested_at: datetime = Field(default_factory=utc_now)


class Evidence(BaseModel):
    document_id: str
    source_id: str
    excerpt: str
    published_at: datetime
    url: str | None = None


class Thesis(BaseModel):
    thesis_id: str
    thesis: str
    theme: str
    horizon: str
    direction: ViewDirection
    assets: list[str] = Field(default_factory=list)
    catalysts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    implied_positioning: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    freshness_score: float = Field(default=0.5, ge=0.0, le=1.0)
    status: ThesisStatus = ThesisStatus.active
    source_ids: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    extracted_at: datetime = Field(default_factory=utc_now)


class MarketObservation(BaseModel):
    observation_id: str
    market: str
    metric: str
    value: str
    as_of: datetime = Field(default_factory=utc_now)
    interpretation: str | None = None
    source: str | None = None


class MarketValidation(BaseModel):
    thesis_id: str
    support_score: float = Field(default=0.5, ge=0.0, le=1.0)
    sentiment_alignment: Literal["supportive", "mixed", "contradictory", "unknown"] = "unknown"
    cross_asset_confirmation: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    observations: list[MarketObservation] = Field(default_factory=list)


class ValidatedThesis(BaseModel):
    thesis: Thesis
    validation: MarketValidation


class PositioningRecommendation(BaseModel):
    recommendation_id: str
    title: str
    rationale: str
    horizon: str
    expression: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    linked_thesis_ids: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class PipelineContext(BaseModel):
    market_observations: list[MarketObservation] = Field(default_factory=list)
    analyst_notes: list[str] = Field(default_factory=list)


class PipelineRunRequest(BaseModel):
    documents: list[RawDocument]
    context: PipelineContext = Field(default_factory=PipelineContext)


class PipelineRunResult(BaseModel):
    documents_ingested: int
    theses_extracted: int
    validated_theses: int = 0
    recommendations_generated: int = 0
    memo_id: str
    memo_path: str | None = None
    generated_at: datetime = Field(default_factory=utc_now)


class PositioningMemo(BaseModel):
    memo_id: str
    title: str
    generated_at: datetime = Field(default_factory=utc_now)
    summary: str
    consensus_views: list[str] = Field(default_factory=list)
    divergent_views: list[str] = Field(default_factory=list)
    suggested_positioning: list[str] = Field(default_factory=list)
    risks_to_watch: list[str] = Field(default_factory=list)
    thesis_ids: list[str] = Field(default_factory=list)
    validation_summary: list[str] = Field(default_factory=list)
    expert_vs_market: list[str] = Field(default_factory=list)
    required_inputs: list[str] = Field(default_factory=list)


SourceDefinition.model_rebuild()

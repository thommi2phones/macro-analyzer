"""Shared types for the macro-brain scoring engine.

Mirrors the framework's §10 trade_score schema and §13 journal models
from the macro-analyzer repo. Single source of truth here so agents +
orchestrator + API surface all speak the same shapes.

Design principles:
- Pydantic v2 throughout
- Internal flat feature vector (0..1 sub-signals) → weighted display
  score (0..100). Flat vector enables future fine-tuning per the
  hybrid-scoring decision.
- Every score artifact carries its `regime_id` so attribution back to
  the regime-at-scoring-time is preserved.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Regimes — both taxonomies (per regime_mapping.json in macro-analyzer)
# ---------------------------------------------------------------------------

ThesisRegime = Literal[
    "war_escalation",
    "inflation_shock",
    "growth_scare",
    "dovish_liquidity_wave",
    "broad_panic",
    "sideways_churn",
    "commodity_expansion",
]

FrameworkRegime = Literal[
    "risk_on_expansion",
    "risk_off_contraction",
    "commodity_led_inflation",
    "monetary_debasement_hard_asset",
    "transitional_chop",
]


class RegimeRead(BaseModel):
    """Output of regime_classifier agent."""

    regime_id: str  # UUID generated client-side
    classified_at: datetime
    thesis_regime: ThesisRegime
    framework_regime: FrameworkRegime
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    classifier_version: str = "regime_classifier@v1"


# ---------------------------------------------------------------------------
# Sub-scores per framework §10 component
# ---------------------------------------------------------------------------

ScoreComponent = Literal[
    "macro_alignment",
    "liquidity_alignment",
    "sector_theme_strength",
    "technical_structure",
    "volume_flow_confirmation",
    "risk_reward_quality",
    "relative_strength",
    "psychological_execution_quality",
]

# Authored weights per framework v1. Sums to 100. Will become learned
# parameters per regime once outcome data accrues.
COMPONENT_WEIGHTS: dict[ScoreComponent, int] = {
    "macro_alignment": 20,
    "liquidity_alignment": 15,
    "sector_theme_strength": 10,
    "technical_structure": 20,
    "volume_flow_confirmation": 15,
    "risk_reward_quality": 10,
    "relative_strength": 5,
    "psychological_execution_quality": 5,
}


class SubScore(BaseModel):
    """One scoring component's output. The flat 0..1 value is the
    primary store; the weighted display value is computed at composition
    time via COMPONENT_WEIGHTS.
    """

    component: ScoreComponent
    value: float = Field(ge=0.0, le=1.0, description="Flat 0..1 sub-signal")
    contributing_features: dict[str, float] = Field(
        default_factory=dict,
        description="Granular features that fed into `value`. Preserved for fine-tuning corpus.",
    )
    notes: str = ""


# ---------------------------------------------------------------------------
# Trade score — composed by orchestrator
# ---------------------------------------------------------------------------

PositionSizeTier = Literal["tier_1", "tier_2", "tier_3", "avoid"]
Grade = Literal["A_plus", "A", "B", "C", "D", "avoid"]


class TradeScore(BaseModel):
    """Output of orchestrator. Mirrors `trade_scores` table in
    macro-analyzer's schema.py.
    """

    score_id: str  # UUID
    setup_id: str | None = None
    regime_id: str | None = None
    scored_at: datetime

    # Component scores (flat vector — primary)
    sub_scores: list[SubScore] = Field(default_factory=list)

    # Weighted display fields (computed)
    macro_alignment_score: int  # 0..20
    liquidity_score: int  # 0..15
    sector_theme_score: int  # 0..10
    technical_structure_score: int  # 0..20
    volume_flow_score: int  # 0..15
    risk_reward_score: int  # 0..10
    relative_strength_score: int  # 0..5
    psychology_score: int  # 0..5
    raw_total_score: int  # 0..100, sum of components
    adjusted_total_score: int  # raw + regime + conservative bias adjustments

    grade: Grade
    position_size_tier: PositionSizeTier

    # Reasoning trail — populated for /explain endpoint
    reasoning_trail: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Inputs to the orchestrator (what /score POST receives)
# ---------------------------------------------------------------------------

class SetupContext(BaseModel):
    """Everything the orchestrator needs to score a setup.

    The macro-analyzer assembles this and POSTs to /score.
    """

    setup_id: str | None = None
    asset_ticker: str
    asset_class: str = "equity"
    setup_type: str = ""

    # Active regime (from regime_classifier or stored in DB)
    active_regime: RegimeRead | None = None

    # Per-thesis & per-source signals — passed into scorers
    relevant_theses: list[dict] = Field(default_factory=list)
    relevant_sources: list[dict] = Field(default_factory=list)

    # Technical/volume features (extracted from chart screenshots, FRED
    # series, or user-supplied levels)
    technical_features: dict = Field(default_factory=dict)
    volume_features: dict = Field(default_factory=dict)

    # User psychology checklist state (per framework §12)
    psychology_state: dict = Field(default_factory=dict)

    # Risk/reward computation inputs
    entry_zone: float | None = None
    stop_loss: float | None = None
    target: float | None = None

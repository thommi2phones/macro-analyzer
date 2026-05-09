"""Composer — assembles agent outputs into a TradeScore per framework §10.

Flow (matches framework §15 analyzer_workflow):
1. Take a SetupContext (regime + theses + sources + technicals + ...)
2. Invoke each scoring agent → get back SubScore objects
3. Convert flat values to weighted display ints (feature_vector module)
4. Apply regime modifier (framework macro_regimes[regime].setup_score_modifier)
5. Apply conservative bias adjustments (framework conservative_bias_adjustments)
6. Assign grade + position_size_tier
7. Wrap in TradeScore with reasoning_trail for /explain endpoint

Phase 4 implementation notes:
- regime modifier + conservative bias use framework v1 defaults; will
  read from config/trading_framework.json once that's mounted/copied
  into this repo's deploy
- Agents are invoked in sequence here; can be parallelized later if
  latency demands it
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from macro_brain.agents.psychology_evaluator.evaluator import (
    score_psychology_execution_quality,
)
from macro_brain.agents.regime_classifier.classifier import (
    score_macro_alignment_from_regime,
)
from macro_brain.agents.technical_scorer.scorer import score_technical_structure
from macro_brain.orchestrator.feature_vector import (
    assign_grade,
    assign_position_size_tier,
    compose_weighted_scores,
    feature_vector_to_dict,
    raw_total,
)
from macro_brain.types import (
    COMPONENT_WEIGHTS,
    SetupContext,
    SubScore,
    TradeScore,
)


# Framework v1 conservative bias adjustments (from trading_framework.json).
# Negative integers applied to raw_total when conditions hit. Will be
# loaded from config in a later iteration.
CONSERVATIVE_BIAS_ADJUSTMENTS: dict[str, int] = {
    "macro_regime_unclear": -10,
    "liquidity_state_contracting": -12,
    "volume_confirmation_weak": -10,
    "invalidation_defined_false": -20,
    "asset_extended_from_support": -10,
    "failed_breakout_recent": -15,
    "risk_reward_lt_2": -12,
}


# Framework v1 regime modifiers (from trading_framework.json macro_regimes).
REGIME_SCORE_MODIFIER: dict[str, int] = {
    "risk_on_expansion": 10,
    "commodity_led_inflation": 8,
    "monetary_debasement_hard_asset": 6,
    "transitional_chop": -8,
    "risk_off_contraction": -15,
}


def _stub_subscore(
    component: str,
    notes: str = "stub — agent not yet implemented",
) -> SubScore:
    """Placeholder for components whose agents aren't built yet.
    Returns a 0.5 neutral value with a note in the reasoning trail.
    Removing these as agents land in Phase 4-6.
    """
    return SubScore(
        component=component,  # type: ignore[arg-type]
        value=0.5,
        contributing_features={},
        notes=notes,
    )


def _compute_risk_reward_subscore(setup: SetupContext) -> SubScore:
    """Heuristic R/R score per framework §9."""
    if setup.entry_zone is None or setup.stop_loss is None or setup.target is None:
        return SubScore(
            component="risk_reward_quality",
            value=0.0,
            contributing_features={"defined": 0.0},
            notes="Risk/reward inputs incomplete (entry/stop/target).",
        )
    risk = abs(setup.entry_zone - setup.stop_loss)
    reward = abs(setup.target - setup.entry_zone)
    if risk == 0:
        return SubScore(component="risk_reward_quality", value=0.0, notes="zero risk")
    rr = reward / risk
    # 1:1 = poor (0.0), 3:1 = excellent (1.0), linear in between
    value = max(0.0, min(1.0, (rr - 1.0) / 2.0))
    return SubScore(
        component="risk_reward_quality",
        value=value,
        contributing_features={"rr_ratio": rr, "risk": risk, "reward": reward},
        notes=f"R/R = {rr:.2f}",
    )


def _apply_conservative_bias(
    raw_score: int,
    setup: SetupContext,
    sub_scores: list[SubScore],
) -> tuple[int, list[str]]:
    """Walk the conservative bias rules, return adjusted score + list
    of which adjustments fired (for the reasoning trail).
    """
    adjusted = raw_score
    applied: list[str] = []

    invalidation_defined = setup.stop_loss is not None
    if not invalidation_defined:
        adjusted += CONSERVATIVE_BIAS_ADJUSTMENTS["invalidation_defined_false"]
        applied.append("invalidation_defined_false")

    if setup.active_regime is None:
        adjusted += CONSERVATIVE_BIAS_ADJUSTMENTS["macro_regime_unclear"]
        applied.append("macro_regime_unclear")

    rr_subscore = next((s for s in sub_scores if s.component == "risk_reward_quality"), None)
    if rr_subscore and rr_subscore.contributing_features.get("rr_ratio", 0.0) < 2.0:
        adjusted += CONSERVATIVE_BIAS_ADJUSTMENTS["risk_reward_lt_2"]
        applied.append("risk_reward_lt_2")

    vol_subscore = next((s for s in sub_scores if s.component == "volume_flow_confirmation"), None)
    if vol_subscore and vol_subscore.value < 0.3:
        adjusted += CONSERVATIVE_BIAS_ADJUSTMENTS["volume_confirmation_weak"]
        applied.append("volume_confirmation_weak")

    return max(0, adjusted), applied


def compose(setup: SetupContext) -> TradeScore:
    """Compose a TradeScore from a SetupContext.

    Phase 4 invokes only the agents that are real:
    - regime_classifier (LLM-stubbed but interface live)
    - psychology_evaluator (heuristic, fully real)
    - risk_reward (heuristic in this module)

    The other 4 components return stub SubScores until their agents
    land in Phase 6.
    """
    sub_scores: list[SubScore] = []

    # Macro alignment — derived from active regime + setup type
    sub_scores.append(score_macro_alignment_from_regime(setup))

    # Liquidity alignment — STUB (depends on regime_classifier reading
    # liquidity_state out of FRED; lands with full regime classifier)
    sub_scores.append(_stub_subscore("liquidity_alignment"))

    # Sector theme — STUB (sector_theme_scorer agent not yet built)
    sub_scores.append(_stub_subscore("sector_theme_strength"))

    # Technical structure — REAL heuristic over price-derived features
    sub_scores.append(score_technical_structure(setup))

    # Volume flow — STUB (volume_analyzer not yet built)
    sub_scores.append(_stub_subscore("volume_flow_confirmation"))

    # Risk/reward — REAL heuristic
    sub_scores.append(_compute_risk_reward_subscore(setup))

    # Relative strength — STUB
    sub_scores.append(_stub_subscore("relative_strength"))

    # Psychology — REAL heuristic
    sub_scores.append(score_psychology_execution_quality(setup))

    # Compose weighted display scores
    weighted = compose_weighted_scores(sub_scores)
    raw = raw_total(weighted)

    # Apply regime modifier
    regime_mod = 0
    if setup.active_regime:
        regime_mod = REGIME_SCORE_MODIFIER.get(setup.active_regime.framework_regime, 0)

    # Apply conservative bias adjustments
    after_regime = max(0, min(100, raw + regime_mod))
    adjusted, adjustments_applied = _apply_conservative_bias(after_regime, setup, sub_scores)
    adjusted = max(0, min(100, adjusted))

    invalidation_defined = setup.stop_loss is not None
    grade = assign_grade(adjusted)
    tier = assign_position_size_tier(adjusted, invalidation_defined=invalidation_defined)

    return TradeScore(
        score_id=str(uuid.uuid4()),
        setup_id=setup.setup_id,
        regime_id=setup.active_regime.regime_id if setup.active_regime else None,
        scored_at=datetime.now(UTC),
        sub_scores=sub_scores,
        macro_alignment_score=weighted["macro_alignment"],
        liquidity_score=weighted["liquidity_alignment"],
        sector_theme_score=weighted["sector_theme_strength"],
        technical_structure_score=weighted["technical_structure"],
        volume_flow_score=weighted["volume_flow_confirmation"],
        risk_reward_score=weighted["risk_reward_quality"],
        relative_strength_score=weighted["relative_strength"],
        psychology_score=weighted["psychological_execution_quality"],
        raw_total_score=raw,
        adjusted_total_score=adjusted,
        grade=grade,  # type: ignore[arg-type]
        position_size_tier=tier,  # type: ignore[arg-type]
        reasoning_trail={
            "raw_total": raw,
            "regime_modifier": regime_mod,
            "regime_modifier_source": setup.active_regime.framework_regime if setup.active_regime else None,
            "conservative_adjustments_applied": adjustments_applied,
            "feature_vector": feature_vector_to_dict(sub_scores),
            "active_thesis_regime": setup.active_regime.thesis_regime if setup.active_regime else None,
            "active_framework_regime": setup.active_regime.framework_regime if setup.active_regime else None,
            "active_regime_confidence": setup.active_regime.confidence if setup.active_regime else None,
            "stub_components": [
                s.component for s in sub_scores if "stub" in s.notes
            ],
        },
    )

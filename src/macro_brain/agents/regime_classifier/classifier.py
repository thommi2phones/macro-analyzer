"""Regime Classifier — currently a stub-with-real-interface.

Phase 4 ships:
- The interface a real implementation will conform to
- A heuristic fallback that derives a regime from active_regime hints
  in the SetupContext (so end-to-end tests work today)
- A score_macro_alignment_from_regime function the orchestrator uses
  to convert "active regime + setup type" into a macro_alignment SubScore

Phase 6 / future will add:
- Real LLM call (via logging_wrapper) reading FRED snapshots + recent
  documents to classify the regime
- Trained classifier (Phase 8) replacing the LLM call

The interface is stable so the orchestrator doesn't need to change
when the implementation does.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from macro_brain.types import RegimeRead, SetupContext, SubScore


# Map (framework_regime, setup_type) → flat alignment score.
# Captures framework v1's macro_regimes[regime].preferred_setups: a setup
# that matches the regime's preferred list scores high; a setup hostile
# to the regime scores low.
#
# Will be replaced by reading config/trading_framework.json once the
# config is mounted into this repo. For now: hand-coded from §2 of the
# framework doc.
PREFERRED_SETUPS: dict[str, set[str]] = {
    "risk_on_expansion": {
        "breakout_continuation", "pullback_to_support", "high_tight_flag",
        "sector_rotation_leader", "relative_strength_continuation",
        "breakout_retest",
    },
    "risk_off_contraction": {
        "failed_breakout_short", "defensive_rotation",
        "mean_reversion_after_capitulation", "cash_preservation",
    },
    "commodity_led_inflation": {
        "commodity_breakout", "miner_relative_strength",
        "uranium_accumulation", "precious_metals_continuation",
    },
    "monetary_debasement_hard_asset": {
        "hard_asset_breakout", "long_base_accumulation",
        "scarcity_asset_pullback", "relative_strength_vs_fiat",
    },
    "transitional_chop": {
        "range_trade", "support_retest", "small_probe", "watchlist_building",
    },
}


def score_macro_alignment_from_regime(setup: SetupContext) -> SubScore:
    """Heuristic macro alignment scorer.

    No active_regime → 0.5 (neutral, with note); orchestrator's
    conservative bias rule will then penalize for unclear regime.

    Setup type matches regime's preferred → 1.0 × confidence
    Setup type does NOT match → 0.3 × confidence (still some signal —
        a non-preferred setup isn't fatal)
    No setup_type provided → 0.5 × confidence
    """
    if setup.active_regime is None:
        return SubScore(
            component="macro_alignment",
            value=0.5,
            contributing_features={"regime_present": 0.0},
            notes="No active regime classified.",
        )

    regime = setup.active_regime
    preferred = PREFERRED_SETUPS.get(regime.framework_regime, set())

    if not setup.setup_type:
        base = 0.5
        match = 0.0
        note = f"No setup_type given against regime {regime.framework_regime}."
    elif setup.setup_type in preferred:
        base = 1.0
        match = 1.0
        note = f"Setup '{setup.setup_type}' is preferred under {regime.framework_regime}."
    else:
        base = 0.3
        match = 0.0
        note = f"Setup '{setup.setup_type}' is NOT preferred under {regime.framework_regime}."

    value = max(0.0, min(1.0, base * regime.confidence))
    return SubScore(
        component="macro_alignment",
        value=value,
        contributing_features={
            "regime_present": 1.0,
            "setup_matches_preferred": match,
            "regime_confidence": regime.confidence,
        },
        notes=note,
    )


def classify_regime_stub(*, hint_thesis_regime: str | None = None) -> RegimeRead:
    """Stub regime classifier. Returns a hand-tagged regime when the
    caller passes a hint, or 'transitional_chop' as a safe default.

    Phase 6 replaces this with a real LLM call (via logging_wrapper)
    that reads FRED + recent documents.
    """
    # Crude mapping for the stub. Real classifier will compute this.
    fallback_thesis = hint_thesis_regime or "sideways_churn"
    fw_map = {
        "war_escalation": "commodity_led_inflation",
        "inflation_shock": "commodity_led_inflation",
        "growth_scare": "risk_off_contraction",
        "dovish_liquidity_wave": "risk_on_expansion",
        "broad_panic": "risk_off_contraction",
        "sideways_churn": "transitional_chop",
        "commodity_expansion": "commodity_led_inflation",
    }
    framework_regime = fw_map.get(fallback_thesis, "transitional_chop")

    return RegimeRead(
        regime_id=str(uuid.uuid4()),
        classified_at=datetime.now(UTC),
        thesis_regime=fallback_thesis,  # type: ignore[arg-type]
        framework_regime=framework_regime,  # type: ignore[arg-type]
        confidence=0.5,
        evidence=["stub classifier — real LLM-backed implementation pending Phase 6"],
        classifier_version="regime_classifier@stub-v0",
    )

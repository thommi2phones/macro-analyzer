"""Tests for orchestrator/composer.py — end-to-end TradeScore composition."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from macro_brain.agents.regime_classifier.classifier import classify_regime_stub
from macro_brain.orchestrator.composer import compose
from macro_brain.types import RegimeRead, SetupContext


def _full_psych_setup(stop_loss=98.0, target=110.0, entry=100.0, regime=None):
    return SetupContext(
        setup_id="setup-test",
        asset_ticker="URNM",
        setup_type="commodity_breakout",
        active_regime=regime,
        entry_zone=entry,
        stop_loss=stop_loss,
        target=target,
        psychology_state={
            "entry_planned_in_advance": True,
            "position_size_predefined": True,
            "setup_matches_playbook": True,
        },
    )


def test_compose_returns_trade_score():
    setup = _full_psych_setup(regime=classify_regime_stub(hint_thesis_regime="commodity_expansion"))
    result = compose(setup)
    assert result.score_id is not None
    assert result.setup_id == "setup-test"
    assert 0 <= result.raw_total_score <= 100
    assert 0 <= result.adjusted_total_score <= 100


def test_compose_preferred_setup_outscores_non_preferred():
    regime = classify_regime_stub(hint_thesis_regime="commodity_expansion")  # → commodity_led_inflation

    pref = _full_psych_setup(regime=regime)
    pref.setup_type = "commodity_breakout"  # in preferred set

    non_pref = _full_psych_setup(regime=regime)
    non_pref.setup_type = "failed_breakout_short"  # NOT in preferred for this regime

    pref_score = compose(pref)
    non_pref_score = compose(non_pref)
    assert pref_score.macro_alignment_score > non_pref_score.macro_alignment_score


def test_compose_no_invalidation_forces_avoid_tier():
    setup = _full_psych_setup(stop_loss=None, regime=classify_regime_stub())
    setup.stop_loss = None
    result = compose(setup)
    assert result.position_size_tier == "avoid"


def test_compose_no_regime_applies_macro_unclear_penalty():
    no_regime = _full_psych_setup(regime=None)
    with_regime = _full_psych_setup(regime=classify_regime_stub(hint_thesis_regime="dovish_liquidity_wave"))
    no_r = compose(no_regime)
    with_r = compose(with_regime)
    # Adjustments applied list should include macro_regime_unclear when no regime
    assert "macro_regime_unclear" in no_r.reasoning_trail["conservative_adjustments_applied"]
    assert "macro_regime_unclear" not in with_r.reasoning_trail["conservative_adjustments_applied"]


def test_compose_reasoning_trail_has_feature_vector():
    setup = _full_psych_setup(regime=classify_regime_stub())
    result = compose(setup)
    fv = result.reasoning_trail["feature_vector"]
    assert "macro_alignment._value" in fv
    assert "psychological_execution_quality._value" in fv


def test_compose_reasoning_trail_lists_stub_components():
    setup = _full_psych_setup(regime=classify_regime_stub())
    result = compose(setup)
    stubs = result.reasoning_trail["stub_components"]
    # Phase 4 stubs: liquidity, sector_theme, technical, volume, relative_strength
    assert "liquidity_alignment" in stubs
    assert "sector_theme_strength" in stubs
    assert "technical_structure" in stubs


def test_compose_grade_threshold_alignment():
    """Sanity: a strong setup gets a non-avoid grade."""
    regime = classify_regime_stub(hint_thesis_regime="commodity_expansion")
    regime.confidence = 1.0  # boost so the macro alignment fires fully
    setup = _full_psych_setup(regime=regime)
    setup.setup_type = "commodity_breakout"
    result = compose(setup)
    # With stubs returning 0.5 for ~5 components, a strong macro+psych+rr
    # should still be in the C/D range (given many sub-scores are still
    # placeholders). The point is just that it's not "avoid".
    assert result.grade in ("A_plus", "A", "B", "C", "D")


def test_risk_reward_subscore_caps_at_3_to_1():
    setup = _full_psych_setup(entry=100, stop_loss=99, target=130)  # rr = 30
    result = compose(setup)
    rr_sub = next(s for s in result.sub_scores if s.component == "risk_reward_quality")
    assert rr_sub.value == 1.0  # clamped


def test_risk_reward_subscore_zero_for_one_to_one():
    setup = _full_psych_setup(entry=100, stop_loss=99, target=101)  # rr = 1
    result = compose(setup)
    rr_sub = next(s for s in result.sub_scores if s.component == "risk_reward_quality")
    assert rr_sub.value == 0.0

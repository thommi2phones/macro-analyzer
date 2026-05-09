"""Tests for psychology_evaluator — pure heuristic, no LLM."""

from __future__ import annotations

import pytest

from macro_brain.agents.psychology_evaluator.evaluator import (
    score_psychology_execution_quality,
)
from macro_brain.types import SetupContext


def _ctx(stop_loss=None, **state):
    return SetupContext(
        asset_ticker="TEST",
        stop_loss=stop_loss,
        psychology_state=state,
    )


def test_all_positives_no_negatives_full_score():
    ctx = _ctx(
        stop_loss=100.0,
        entry_planned_in_advance=True,
        position_size_predefined=True,
        setup_matches_playbook=True,
    )
    sub = score_psychology_execution_quality(ctx)
    assert sub.value == 1.0
    assert sub.component == "psychological_execution_quality"


def test_invalidation_inferred_from_stop_loss():
    ctx = _ctx(
        stop_loss=100.0,
        entry_planned_in_advance=True,
        position_size_predefined=True,
        setup_matches_playbook=True,
        # invalidation_defined NOT set explicitly → should infer from stop_loss
    )
    sub = score_psychology_execution_quality(ctx)
    assert sub.value == 1.0  # all 4 positives still met


def test_three_of_four_positives():
    ctx = _ctx(
        stop_loss=100.0,
        entry_planned_in_advance=True,
        position_size_predefined=True,
        # setup_matches_playbook missing
    )
    sub = score_psychology_execution_quality(ctx)
    assert sub.value == 0.75


def test_zero_positives_zero_negatives():
    ctx = _ctx()  # no flags, no stop_loss → invalidation_defined=False
    sub = score_psychology_execution_quality(ctx)
    assert sub.value == 0.0


def test_fomo_entry_zeroes_score():
    ctx = _ctx(
        stop_loss=100.0,
        entry_planned_in_advance=True,
        position_size_predefined=True,
        setup_matches_playbook=True,
        fomo_entry=True,
    )
    sub = score_psychology_execution_quality(ctx)
    assert sub.value == 0.0
    assert "Negative execution state" in sub.notes


def test_revenge_sizing_zeroes_score():
    ctx = _ctx(
        stop_loss=100.0,
        entry_planned_in_advance=True,
        position_size_predefined=True,
        setup_matches_playbook=True,
        revenge_sizing=True,
    )
    sub = score_psychology_execution_quality(ctx)
    assert sub.value == 0.0


def test_contributing_features_capture_each_flag():
    ctx = _ctx(
        stop_loss=100.0,
        entry_planned_in_advance=True,
        fomo_entry=True,
    )
    sub = score_psychology_execution_quality(ctx)
    feats = sub.contributing_features
    assert feats["entry_planned_in_advance"] == 1.0
    assert feats["invalidation_defined"] == 1.0  # inferred from stop_loss
    assert feats["position_size_predefined"] == 0.0
    assert feats["fomo_entry"] == 1.0

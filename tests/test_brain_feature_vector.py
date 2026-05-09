"""Tests for orchestrator/feature_vector.py — pure functions."""

from __future__ import annotations

import pytest

from macro_brain.orchestrator.feature_vector import (
    assign_grade,
    assign_position_size_tier,
    compose_weighted_scores,
    feature_vector_to_dict,
    raw_total,
    to_weighted_int,
)
from macro_brain.types import COMPONENT_WEIGHTS, SubScore


def test_to_weighted_int_max_value():
    assert to_weighted_int("macro_alignment", 1.0) == 20  # full 20pt weight
    assert to_weighted_int("liquidity_alignment", 1.0) == 15
    assert to_weighted_int("relative_strength", 1.0) == 5


def test_to_weighted_int_zero():
    assert to_weighted_int("macro_alignment", 0.0) == 0


def test_to_weighted_int_partial():
    assert to_weighted_int("macro_alignment", 0.5) == 10
    assert to_weighted_int("technical_structure", 0.85) == 17  # round(17.0)


def test_to_weighted_int_clamps_negative():
    assert to_weighted_int("macro_alignment", -0.5) == 0


def test_to_weighted_int_clamps_above_one():
    assert to_weighted_int("macro_alignment", 1.5) == 20


def test_compose_weighted_scores_full_set():
    sub_scores = [
        SubScore(component=c, value=1.0) for c in COMPONENT_WEIGHTS
    ]
    weighted = compose_weighted_scores(sub_scores)
    assert sum(weighted.values()) == 100


def test_compose_weighted_scores_missing_components_zero():
    sub_scores = [SubScore(component="macro_alignment", value=1.0)]
    weighted = compose_weighted_scores(sub_scores)
    assert weighted["macro_alignment"] == 20
    assert weighted["liquidity_alignment"] == 0
    assert weighted["psychological_execution_quality"] == 0


def test_raw_total_sums_components():
    weighted = compose_weighted_scores(
        [
            SubScore(component="macro_alignment", value=0.5),  # 10
            SubScore(component="liquidity_alignment", value=1.0),  # 15
            SubScore(component="psychological_execution_quality", value=1.0),  # 5
        ]
    )
    assert raw_total(weighted) == 30


def test_assign_grade_thresholds():
    assert assign_grade(95) == "A_plus"
    assert assign_grade(90) == "A_plus"
    assert assign_grade(85) == "A"
    assert assign_grade(75) == "B"
    assert assign_grade(65) == "C"
    assert assign_grade(55) == "D"
    assert assign_grade(40) == "avoid"


def test_assign_position_size_tier_no_invalidation_always_avoid():
    assert assign_position_size_tier(95, invalidation_defined=False) == "avoid"


def test_assign_position_size_tier_thresholds_with_invalidation():
    assert assign_position_size_tier(90, invalidation_defined=True) == "tier_1"
    assert assign_position_size_tier(75, invalidation_defined=True) == "tier_2"
    assert assign_position_size_tier(60, invalidation_defined=True) == "tier_3"
    assert assign_position_size_tier(45, invalidation_defined=True) == "avoid"


def test_feature_vector_to_dict_includes_components_and_subfeatures():
    sub_scores = [
        SubScore(
            component="macro_alignment",
            value=0.8,
            contributing_features={"regime_present": 1.0, "regime_confidence": 0.9},
        ),
        SubScore(component="liquidity_alignment", value=0.5),
    ]
    fv = feature_vector_to_dict(sub_scores)
    assert fv["macro_alignment._value"] == 0.8
    assert fv["macro_alignment.regime_present"] == 1.0
    assert fv["macro_alignment.regime_confidence"] == 0.9
    assert fv["liquidity_alignment._value"] == 0.5

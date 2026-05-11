"""Tests for rules/confluence.py — 0..8 rubric + tier mapping."""

from __future__ import annotations

import pytest

from macro_positioning.rules import reset_caches
from macro_positioning.rules.confluence import (
    from_legacy_score,
    score_confluence,
    tier_for_score,
)


@pytest.fixture(autouse=True)
def _clear_caps_cache():
    reset_caches()
    yield
    reset_caches()


def test_score_confluence_sums_and_clamps():
    b = score_confluence(3, 3, 2)
    assert (b.pattern, b.fib, b.indicator, b.total) == (3, 3, 2, 8)
    assert b.tier == "high_conviction"


def test_clamp_keeps_subscores_in_band():
    b = score_confluence(99, -5, 7)
    assert b.pattern == 3
    assert b.fib == 0
    assert b.indicator == 2


def test_tier_thresholds_match_caps():
    # From config/risk_caps.json: insufficient<=4, standard>=5, high_conviction>=7
    assert tier_for_score(0) == "insufficient"
    assert tier_for_score(4) == "insufficient"
    assert tier_for_score(5) == "standard"
    assert tier_for_score(6) == "standard"
    assert tier_for_score(7) == "high_conviction"
    assert tier_for_score(8) == "high_conviction"


def test_from_legacy_score_maps_extremes():
    assert from_legacy_score(1).total == 1
    assert from_legacy_score(1).tier == "insufficient"
    assert from_legacy_score(5).total == 8
    assert from_legacy_score(5).tier == "high_conviction"


def test_from_legacy_score_rejects_out_of_band():
    with pytest.raises(ValueError):
        from_legacy_score(0)
    with pytest.raises(ValueError):
        from_legacy_score(6)


def test_as_dict_roundtrip():
    b = score_confluence(2, 1, 1)
    d = b.as_dict()
    assert d == {"pattern": 2, "fib": 1, "indicator": 1, "total": 4, "tier": "insufficient"}

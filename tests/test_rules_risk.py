"""Tests for rules/risk.py — account-risk-% + sizing + stop-direction."""

from __future__ import annotations

import pytest

from macro_positioning.rules import reset_caches
from macro_positioning.rules.risk import (
    account_risk_pct,
    recommended_size,
    validate_sizing,
    validate_stop_direction,
)


@pytest.fixture(autouse=True)
def _clear_caps_cache():
    reset_caches()
    yield
    reset_caches()


def test_account_risk_pct_basic():
    # entry 100, stop 95, 10 units, equity 100000 → 5*10/100000 = 0.0005 = 0.05%
    assert account_risk_pct(100.0, 95.0, 10.0, 100_000.0) == pytest.approx(0.0005)


def test_account_risk_pct_direction_agnostic():
    # short trade: entry 95, stop 100 (stop above entry) — same |distance|
    assert account_risk_pct(95.0, 100.0, 10.0, 100_000.0) == pytest.approx(0.0005)


def test_account_risk_pct_zero_distance_returns_zero():
    assert account_risk_pct(100.0, 100.0, 10.0, 100_000.0) == 0.0


def test_account_risk_pct_invalid_inputs():
    with pytest.raises(ValueError):
        account_risk_pct(100.0, 95.0, 10.0, 0.0)
    with pytest.raises(ValueError):
        account_risk_pct(100.0, 95.0, -1.0, 100_000.0)


def test_recommended_size_hits_target_risk():
    # equity 100000, target 1% = 1000, stop distance 5 → size = 1000/5 = 200
    size = recommended_size(100.0, 95.0, 100_000.0, target_risk_pct=0.01)
    assert size == pytest.approx(200.0)
    # And that size, when fed back, recovers the target risk
    assert account_risk_pct(100.0, 95.0, size, 100_000.0) == pytest.approx(0.01)


def test_recommended_size_default_from_caps():
    # caps.trade_level.max_account_risk_per_trade_pct = 0.01
    assert recommended_size(100.0, 95.0, 100_000.0) == pytest.approx(200.0)


def test_validate_stop_direction_long_wrong_side():
    v = validate_stop_direction("long", entry=100.0, stop=101.0)
    assert v is not None and v.code == "stop_on_wrong_side"
    assert v.severity == "hard"


def test_validate_stop_direction_short_wrong_side():
    v = validate_stop_direction("short", entry=100.0, stop=99.0)
    assert v is not None and v.code == "stop_on_wrong_side"


def test_validate_stop_direction_correct():
    assert validate_stop_direction("long", 100.0, 95.0) is None
    assert validate_stop_direction("short", 100.0, 105.0) is None


def test_validate_sizing_insufficient_short_circuits():
    out = validate_sizing(0.0001, "insufficient", allocation_pct=0.04)
    assert len(out) == 1
    assert out[0].code == "confluence_insufficient"


def test_validate_sizing_account_risk_exceeded_standard():
    # caps: standard max 0.01. Pass 0.012 → violation
    out = validate_sizing(0.012, "standard")
    codes = {v.code for v in out}
    assert "account_risk_exceeded" in codes


def test_validate_sizing_high_conviction_has_higher_cap():
    # 0.012 ok for high_conviction (cap 0.015) but not for standard (cap 0.01)
    assert all(v.code != "account_risk_exceeded" for v in validate_sizing(0.012, "high_conviction"))
    assert any(v.code == "account_risk_exceeded" for v in validate_sizing(0.012, "standard"))


def test_validate_sizing_allocation_above_absolute_ceiling():
    # 0.09 > 0.08 high_conviction ceiling
    out = validate_sizing(0.005, "standard", allocation_pct=0.09)
    codes = {v.code for v in out}
    assert "allocation_above_high_conviction_ceiling" in codes


def test_validate_sizing_allocation_below_floor():
    out = validate_sizing(0.005, "standard", allocation_pct=0.02)
    codes = {v.code for v in out}
    assert "allocation_below_standard_floor" in codes


def test_validate_sizing_clean_trade_no_violations():
    # standard tier, 0.5% risk, 4% allocation → all caps OK
    out = validate_sizing(0.005, "standard", allocation_pct=0.04)
    assert out == []

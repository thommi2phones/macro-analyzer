"""Tests for volume_flow_confirmation heuristic scorer."""

from __future__ import annotations

from macro_brain.agents.volume_analyzer.scorer import (
    score_volume_flow_confirmation,
)
from macro_brain.types import SetupContext


def _ctx(**vol):
    return SetupContext(asset_ticker="TEST", volume_features=vol)


def test_rally_with_volume_expansion_scores_above_neutral():
    ctx = _ctx(
        n_volume_bars=50,
        vol_5d_avg=2_000_000.0,
        vol_20d_avg=1_000_000.0,  # 2.0x ratio
        pct_change_5d=0.04,
    )
    sub = score_volume_flow_confirmation(ctx)
    assert sub.component == "volume_flow_confirmation"
    assert sub.value > 0.7
    assert "confirms" in sub.notes


def test_rally_with_volume_fade_scores_below_neutral():
    ctx = _ctx(
        n_volume_bars=50,
        vol_5d_avg=500_000.0,
        vol_20d_avg=1_000_000.0,
        pct_change_5d=0.03,
    )
    sub = score_volume_flow_confirmation(ctx)
    assert sub.value < 0.4


def test_distribution_pattern_scores_below_neutral():
    """Heavy volume on a sell-off → bearish for a long-bias setup."""
    ctx = _ctx(
        n_volume_bars=50,
        vol_5d_avg=2_000_000.0,
        vol_20d_avg=1_000_000.0,
        pct_change_5d=-0.05,
    )
    sub = score_volume_flow_confirmation(ctx)
    assert sub.value < 0.3


def test_missing_volume_history_returns_neutral():
    ctx = _ctx(n_volume_bars=10)
    sub = score_volume_flow_confirmation(ctx)
    assert sub.value == 0.5
    assert "Insufficient" in sub.notes


def test_zero_volume_day_does_not_crash():
    ctx = _ctx(
        n_volume_bars=50,
        vol_5d_avg=0.0,
        vol_20d_avg=0.0,
        pct_change_5d=0.0,
    )
    sub = score_volume_flow_confirmation(ctx)
    assert sub.value == 0.5

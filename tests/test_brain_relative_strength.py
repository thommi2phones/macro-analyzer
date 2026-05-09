"""Tests for relative_strength heuristic scorer."""

from __future__ import annotations

from macro_brain.agents.relative_strength.scorer import score_relative_strength
from macro_brain.types import SetupContext


def _ctx(ticker_pct, bench_pct, bench="SPY"):
    return SetupContext(
        asset_ticker="TEST",
        relative_strength_features={
            "ticker_pct20d": ticker_pct,
            "benchmark_pct20d": bench_pct,
            "benchmark_ticker": bench,
        },
    )


def test_outperformance_scores_high():
    sub = score_relative_strength(_ctx(0.15, 0.05))  # +10pp diff
    assert sub.component == "relative_strength"
    assert sub.value > 0.85


def test_underperformance_scores_low():
    sub = score_relative_strength(_ctx(-0.05, 0.05))  # -10pp diff
    assert sub.value < 0.15


def test_parity_scores_neutral():
    sub = score_relative_strength(_ctx(0.05, 0.05))
    assert abs(sub.value - 0.5) < 0.01


def test_missing_benchmark_data_returns_neutral():
    sub = score_relative_strength(_ctx(0.05, None))
    assert sub.value == 0.5
    assert "Insufficient" in sub.notes


def test_zero_returns_both_sides_returns_neutral():
    sub = score_relative_strength(_ctx(0.0, 0.0))
    assert abs(sub.value - 0.5) < 0.01

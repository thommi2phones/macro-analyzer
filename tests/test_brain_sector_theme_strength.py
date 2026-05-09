"""Tests for sector_theme_strength heuristic scorer."""

from __future__ import annotations

from macro_brain.agents.sector_theme_scorer.scorer import (
    score_sector_theme_strength,
)
from macro_brain.types import SetupContext


def _ctx(asset_themes, theme_signals, scale):
    return SetupContext(
        asset_ticker="URA",
        theme_signals={
            "asset_themes": asset_themes,
            "theme_signals": theme_signals,
            "scale": scale,
        },
    )


def test_strong_theme_scores_high():
    ctx = _ctx(
        asset_themes=["uranium"],
        theme_signals={"uranium": 8.0, "gold": 1.0},
        scale=2.0,
    )
    sub = score_sector_theme_strength(ctx)
    assert sub.component == "sector_theme_strength"
    assert sub.value > 0.95  # tanh(4) ~ 0.999


def test_weak_theme_scores_low_but_positive():
    ctx = _ctx(
        asset_themes=["uranium"],
        theme_signals={"uranium": 0.3, "gold": 5.0},
        scale=4.0,
    )
    sub = score_sector_theme_strength(ctx)
    assert 0.0 < sub.value < 0.2


def test_ticker_with_no_themes_returns_neutral():
    ctx = _ctx(asset_themes=[], theme_signals={"uranium": 5.0}, scale=3.0)
    sub = score_sector_theme_strength(ctx)
    assert sub.value == 0.5
    assert "not mapped" in sub.notes


def test_zero_activity_window_returns_neutral():
    ctx = _ctx(
        asset_themes=["uranium"],
        theme_signals={"uranium": 0.0, "gold": 0.0},
        scale=0.0,
    )
    sub = score_sector_theme_strength(ctx)
    assert sub.value == 0.5


def test_multi_theme_picks_strongest():
    ctx = _ctx(
        asset_themes=["uranium", "gold"],
        theme_signals={"uranium": 0.5, "gold": 4.0},
        scale=2.0,
    )
    sub = score_sector_theme_strength(ctx)
    assert sub.contributing_features["best_score"] == 4.0

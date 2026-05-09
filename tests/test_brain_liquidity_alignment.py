"""Tests for liquidity_alignment heuristic scorer."""

from __future__ import annotations

from macro_brain.agents.liquidity_alignment.scorer import score_liquidity_alignment
from macro_brain.types import SetupContext


def _ctx(**feats):
    return SetupContext(asset_ticker="TEST", liquidity_features=feats)


def test_easing_aligns_with_bullish_regime_high_score():
    sub = score_liquidity_alignment(
        _ctx(
            nfci_latest=-0.4,
            nfci_4w_change=-0.3,
            regime_bullish=True,
            source="fred:NFCI",
        )
    )
    assert sub.component == "liquidity_alignment"
    assert sub.value > 0.7


def test_tightening_against_bullish_regime_low_score():
    sub = score_liquidity_alignment(
        _ctx(
            nfci_latest=0.4,
            nfci_4w_change=0.3,
            regime_bullish=True,
            source="fred:NFCI",
        )
    )
    assert sub.value < 0.3


def test_tightening_aligns_with_bearish_regime_high_score():
    sub = score_liquidity_alignment(
        _ctx(
            nfci_latest=0.4,
            nfci_4w_change=0.3,
            regime_bullish=False,
            source="fred:NFCI",
        )
    )
    assert sub.value > 0.7


def test_missing_fci_returns_neutral():
    sub = score_liquidity_alignment(_ctx(source="missing"))
    assert sub.value == 0.5
    assert "No FCI" in sub.notes


def test_only_change_present_still_scores():
    """Edge case: nfci_latest absent but 4w change is known."""
    sub = score_liquidity_alignment(
        _ctx(nfci_4w_change=-0.5, regime_bullish=True, source="fred:NFCI")
    )
    assert sub.value > 0.5

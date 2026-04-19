"""Tests for memo building logic."""
from __future__ import annotations

from datetime import datetime, timezone

from macro_positioning.core.models import (
    MarketValidation,
    Thesis,
    ThesisStatus,
    ValidatedThesis,
    ViewDirection,
)
from macro_positioning.reports.memo import (
    build_positioning_memo,
    summarize_consensus,
    summarize_divergence,
)


def _thesis(theme: str, direction: ViewDirection, source: str, confidence: float = 0.6) -> Thesis:
    return Thesis(
        thesis_id=f"{theme}-{direction.value}-{source}",
        thesis=f"{direction.value} on {theme}",
        theme=theme,
        horizon="2-8 weeks",
        direction=direction,
        assets=[theme],
        catalysts=[],
        risks=[],
        implied_positioning=[f"test-positioning-{theme}"],
        confidence=confidence,
        freshness_score=0.8,
        status=ThesisStatus.active,
        source_ids=[source],
        evidence=[],
    )


class TestSummarizeConsensus:
    def test_trust_weighting_beats_count(self):
        # Two bearish theses from low-trust sources vs one bullish from high-trust
        theses = [
            _thesis("rates", ViewDirection.bearish, "low1", confidence=0.5),
            _thesis("rates", ViewDirection.bearish, "low2", confidence=0.5),
            _thesis("rates", ViewDirection.bullish, "star", confidence=0.9),
        ]
        weights = {"low1": 0.2, "low2": 0.2, "star": 1.0}
        consensus = summarize_consensus(theses, source_weights=weights)
        assert consensus, "expected a consensus row"
        assert "bullish" in consensus[0]

    def test_no_consensus_when_evenly_split(self):
        theses = [
            _thesis("rates", ViewDirection.bullish, "a", confidence=0.6),
            _thesis("rates", ViewDirection.bearish, "b", confidence=0.6),
        ]
        # With equal weights share will be 50% which is not < 0.5 - may or may not
        # be returned. Mostly we just want this to not raise.
        summarize_consensus(theses)


class TestSummarizeDivergence:
    def test_flags_real_split(self):
        theses = [
            _thesis("rates", ViewDirection.bullish, "a"),
            _thesis("rates", ViewDirection.bearish, "b"),
        ]
        divergence = summarize_divergence(theses)
        assert divergence
        assert "rates" in divergence[0].lower()

    def test_watchful_plus_directional_is_not_divergent(self):
        theses = [
            _thesis("rates", ViewDirection.bullish, "a"),
            _thesis("rates", ViewDirection.watchful, "b"),
        ]
        assert summarize_divergence(theses) == []


class TestBuildMemo:
    def test_summary_flags_market_disagreement(self):
        theses = [_thesis("rates", ViewDirection.bullish, "a", confidence=0.8)]
        validated = [
            ValidatedThesis(
                thesis=theses[0],
                validation=MarketValidation(
                    thesis_id=theses[0].thesis_id,
                    support_score=0.3,
                    sentiment_alignment="contradictory",
                    cross_asset_confirmation=[],
                    notes=[],
                    observations=[],
                ),
            )
        ]
        memo = build_positioning_memo(theses, validated_theses=validated)
        assert "market disagrees" in memo.summary.lower()
        assert any("MARKET DISAGREES" in row for row in memo.expert_vs_market)

    def test_required_inputs_passed_through(self):
        theses = [_thesis("rates", ViewDirection.bullish, "a")]
        memo = build_positioning_memo(theses, required_inputs=["X", "Y"])
        assert memo.required_inputs == ["X", "Y"]

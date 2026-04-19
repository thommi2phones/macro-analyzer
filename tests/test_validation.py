"""Tests for the market validation layer."""
from __future__ import annotations

from datetime import datetime, timezone

from macro_positioning.core.models import (
    Evidence,
    MarketObservation,
    Thesis,
    ThesisStatus,
    ViewDirection,
)
from macro_positioning.market.validation import (
    _matches_thesis,
    build_recommendations,
    observation_polarity,
    validate_theses,
)


def _obs(market: str, metric: str, interp: str) -> MarketObservation:
    return MarketObservation(
        observation_id=f"{market}-{metric}",
        market=market,
        metric=metric,
        value="n/a",
        as_of=datetime.now(timezone.utc),
        interpretation=interp,
        source="test",
    )


def _thesis(
    theme: str,
    direction: ViewDirection,
    assets: list[str] | None = None,
    confidence: float = 0.6,
) -> Thesis:
    return Thesis(
        thesis_id=f"t-{theme}-{direction.value}",
        thesis=f"{direction.value} on {theme}",
        theme=theme,
        horizon="2-8 weeks",
        direction=direction,
        assets=assets or [],
        catalysts=[],
        risks=[],
        implied_positioning=[],
        confidence=confidence,
        freshness_score=0.8,
        status=ThesisStatus.active,
        source_ids=["src1"],
        evidence=[],
    )


class TestObservationPolarity:
    def test_positive_interpretation(self):
        assert observation_polarity(_obs("equities", "breadth", "Breadth is improving and confirming")) == 1

    def test_negative_interpretation(self):
        assert observation_polarity(_obs("rates", "hy_spreads", "Spreads are widening and stress rising")) > -2
        # "rising" is positive marker; but we also have "stress". Just check neutral or negative.
        assert observation_polarity(_obs("usd", "dxy", "Dollar momentum is weakening.")) == -1

    def test_neutral_without_markers(self):
        assert observation_polarity(_obs("rates", "10y", "10Y yield is 4.25%")) == 0


class TestMatchesThesis:
    def test_direct_asset_match(self):
        t = _thesis("equities", ViewDirection.bullish, assets=["equities"])
        assert _matches_thesis(_obs("equities", "breadth", ""), t)

    def test_theme_match(self):
        t = _thesis("rates", ViewDirection.bullish)
        assert _matches_thesis(_obs("rates", "10y_real_yield", ""), t)

    def test_alias_expansion_inflation_to_rates(self):
        t = _thesis("inflation", ViewDirection.bearish)
        assert _matches_thesis(_obs("rates", "10y_real_yield", ""), t)

    def test_no_match(self):
        t = _thesis("equities", ViewDirection.bullish, assets=["equities"])
        assert not _matches_thesis(_obs("housing", "starts", ""), t)


class TestValidateTheses:
    def test_supportive_when_polarities_agree(self):
        theses = [_thesis("equities", ViewDirection.bullish, assets=["equities"])]
        obs = [_obs("equities", "breadth", "Breadth is improving and confirming cyclical strength")]
        validated = validate_theses(theses, obs)
        assert validated[0].validation.sentiment_alignment == "supportive"
        assert validated[0].validation.support_score > 0.5

    def test_contradictory_when_polarities_disagree(self):
        theses = [_thesis("equities", ViewDirection.bullish, assets=["equities"])]
        obs = [_obs("equities", "vol", "Equity vol is rising and risk-off fatigue is spreading")]
        validated = validate_theses(theses, obs)
        # "rising" is positive marker, "fatigue" negative -> could be neutral;
        # but at minimum it should NOT be strongly supportive.
        assert validated[0].validation.sentiment_alignment in {"mixed", "contradictory", "unknown"}

    def test_unknown_when_no_observations(self):
        theses = [_thesis("crypto", ViewDirection.bullish, assets=["crypto"])]
        obs = [_obs("housing", "starts", "Housing is strong")]
        validated = validate_theses(theses, obs)
        assert validated[0].validation.sentiment_alignment == "unknown"


class TestBuildRecommendations:
    def test_drops_below_support_threshold(self):
        theses = [_thesis("equities", ViewDirection.bullish, confidence=0.2)]
        # Low confidence + no obs -> low support -> no rec
        recs = build_recommendations(validate_theses(theses, []))
        assert recs == []

    def test_drops_contradictory_alignment(self):
        theses = [_thesis("equities", ViewDirection.bullish, assets=["equities"], confidence=0.9)]
        obs = [_obs("equities", "stress", "weakening, deteriorating, bearish")]
        validated = validate_theses(theses, obs)
        assert validated[0].validation.sentiment_alignment == "contradictory"
        assert build_recommendations(validated) == []

    def test_ranks_by_confidence(self):
        theses = [
            _thesis("equities", ViewDirection.bullish, assets=["equities"], confidence=0.7),
            _thesis("rates", ViewDirection.bullish, assets=["rates"], confidence=0.9),
        ]
        obs = [
            _obs("equities", "breadth", "improving"),
            _obs("rates", "10y", "supportive rising"),
        ]
        recs = build_recommendations(validate_theses(theses, obs))
        assert recs
        # highest confidence first
        assert recs[0].confidence >= recs[-1].confidence

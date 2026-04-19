"""Tests for the heuristic thesis extractor."""
from __future__ import annotations

from datetime import datetime, timezone

from macro_positioning.core.models import ViewDirection
from macro_positioning.brain.heuristic import (
    HeuristicThesisExtractor,
    infer_assets,
    infer_direction,
    infer_horizon,
    infer_theme,
    split_sentences,
)


def _run_extractor(text: str):
    extractor = HeuristicThesisExtractor(min_confidence=0.30)
    return extractor.extract(
        document_id="doc1",
        source_id="src1",
        text=text,
        published_at=datetime.now(timezone.utc),
        url=None,
    )


class TestSplitSentences:
    def test_splits_on_terminal_punctuation(self):
        text = "First sentence. Second sentence! Third sentence?"
        assert split_sentences(text) == [
            "First sentence.",
            "Second sentence!",
            "Third sentence?",
        ]

    def test_drops_very_short_fragments(self):
        text = "Hi. This is a real sentence about growth."
        assert split_sentences(text) == ["This is a real sentence about growth."]


class TestInferDirection:
    def test_bullish_word(self):
        assert infer_direction("We are bullish on equities.") == ViewDirection.bullish

    def test_bearish_word(self):
        assert infer_direction("Bonds are rolling over here.") == ViewDirection.bearish

    def test_negation_flips_polarity(self):
        # "not supportive" should NOT count as bullish
        assert infer_direction("The setup is not supportive for duration.") != ViewDirection.bullish

    def test_watchful_when_no_direction(self):
        assert infer_direction("We will monitor inflation carefully.") == ViewDirection.watchful

    def test_none_on_neutral_statement(self):
        assert infer_direction("The Fed meets next week.") is None


class TestAssetsAndTheme:
    def test_detects_rates_from_duration(self):
        assert "rates" in infer_assets("long duration position")

    def test_detects_multiple_assets(self):
        assets = infer_assets("We like gold and equities here.")
        assert "gold" in assets
        assert "equities" in assets

    def test_theme_prefers_macro_label(self):
        assert infer_theme("growth is slowing rapidly", ["rates"]) == "growth"

    def test_theme_falls_back_to_asset(self):
        assert infer_theme("we prefer gold", ["gold"]) == "gold"


class TestInferHorizon:
    def test_tactical_to_weeks(self):
        assert infer_horizon("a tactical long position") == "2-8 weeks"

    def test_structural_to_long(self):
        assert infer_horizon("a structural long call") == "6-18 months"

    def test_quarter_to_months(self):
        assert infer_horizon("over the next quarter") == "1-3 months"


class TestExtractorEndToEnd:
    def test_extracts_thesis_from_bullish_text(self):
        text = (
            "We think equity breadth is improving and a tactical long in equities works. "
            "Our base case is bullish for the next several weeks."
        )
        theses = _run_extractor(text)
        assert theses, "expected at least one thesis"
        assert any(t.direction == ViewDirection.bullish for t in theses)
        assert any("equities" in t.assets for t in theses)

    def test_drops_low_confidence_unassertive_text(self):
        text = "The weather is nice today. Python is fun."
        assert _run_extractor(text) == []

    def test_dedupes_identical_sentences(self):
        text = "We are bullish on gold. We are bullish on gold."
        theses = _run_extractor(text)
        assert len(theses) == 1

    def test_populates_evidence_and_risks(self):
        text = (
            "We are bullish on equities and prefer cyclicals. "
            "The risk is that financial conditions tighten."
        )
        theses = _run_extractor(text)
        assert theses[0].evidence
        assert theses[0].evidence[0].document_id == "doc1"
        assert any("tighten" in risk for t in theses for risk in t.risks)

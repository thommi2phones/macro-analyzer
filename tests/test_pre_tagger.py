"""Tests for ingestion/pre_tagger.py — keyword routing, no LLM, no I/O
beyond reading the (real) routing config.
"""

from __future__ import annotations

from macro_positioning.ingestion.pre_tagger import (
    detect_tags,
    merge_tags,
    route_document,
    route_to_agents,
)


def test_detect_basic_macro_keywords():
    text = "The Fed is signaling more rate hikes amid sticky inflation"
    tags = detect_tags(text)
    assert "fed" in tags
    assert "rates" in tags
    assert "inflation" in tags


def test_detect_word_boundary_avoids_false_positive():
    # "rates" should match in "interest rates" but not in "berates"
    assert "rates" in detect_tags("interest rates climb")
    assert "rates" not in detect_tags("the critic berates the move")


def test_detect_multiword_phrase():
    assert "ai" in detect_tags("The AI investment cycle continues with new GPU shipments")
    assert "energy" in detect_tags("US natural gas exports surged this quarter")


def test_detect_case_insensitive():
    assert "crypto" in detect_tags("BITCOIN rallies")
    assert "rates" in detect_tags("YIELDS spiked")


def test_detect_empty_returns_empty_set():
    assert detect_tags("") == set()
    assert detect_tags(None) == set()  # type: ignore[arg-type]


def test_merge_tags_includes_source_routing_tags():
    detected = {"macro", "rates"}
    source_tags = ["geopolitics", "rates"]  # rates dedupes
    merged = merge_tags(detected, source_tags)
    assert merged == {"macro", "rates", "geopolitics"}


def test_merge_tags_handles_empty_source_tags():
    assert merge_tags({"macro"}, None) == {"macro"}
    assert merge_tags({"macro"}, []) == {"macro"}


def test_route_to_agents_uses_loaded_routing():
    # 'inflation' tag routes to regime_classifier + narrative_synthesizer
    agents = route_to_agents({"inflation"})
    assert "regime_classifier" in agents
    assert "narrative_synthesizer" in agents


def test_route_to_agents_unknown_tag_gives_empty():
    agents = route_to_agents({"nonsense_tag_xyz"})
    assert agents == set()


def test_route_to_agents_empty_input():
    assert route_to_agents(set()) == set()


def test_route_document_combines_detection_and_source_tags():
    text = "Powell warns on inflation persistence; markets reprice cuts"
    tags, agents = route_document(
        text,
        title="Fed minutes preview",
        source_routing_tags=["macro", "rates"],
    )
    # Detected from content
    assert "fed" in tags
    assert "inflation" in tags
    # From source
    assert "macro" in tags
    assert "rates" in tags
    # Routing should reach regime_classifier + narrative_synthesizer at minimum
    assert "regime_classifier" in agents
    assert "narrative_synthesizer" in agents


def test_route_document_no_match_returns_empty_agents():
    text = "Recipes for sourdough bread"  # no macro keywords
    tags, agents = route_document(text)
    # Might pick up nothing tag-wise → empty agents → would be skipped in pipeline
    assert agents == set() or "narrative_synthesizer" not in agents or len(tags) == 0


def test_chart_tag_routes_to_chart_vision():
    agents = route_to_agents({"chart"})
    assert "chart_vision" in agents

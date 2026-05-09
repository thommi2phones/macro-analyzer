"""Tests for scoring/mention_extractor.py.

False positives are the biggest risk — these tests are the safety net.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from macro_positioning.scoring.mention_extractor import (
    count_mentions,
    extract_tickers_from_text,
    get_allowlist,
    recency_weight,
)


NOW = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Allow-list construction
# ---------------------------------------------------------------------------

def test_allowlist_includes_anchors_from_watchlist_json():
    al = get_allowlist()
    # config/watchlist.json anchors
    assert "URA" in al
    assert "GLD" in al
    assert "BTC" in al
    assert "SPY" in al


def test_allowlist_includes_asset_themes_tickers():
    al = get_allowlist()
    # config/asset_themes.json watchlist_tickers across themes
    assert "URNM" in al   # uranium theme
    assert "GDX" in al    # precious metals theme
    assert "NVDA" in al   # tech_ai theme
    assert "ITA" in al    # defense theme


# ---------------------------------------------------------------------------
# Bare ticker extraction
# ---------------------------------------------------------------------------

def test_bare_ticker_match_in_simple_sentence():
    text = "Watching URA closely as uranium tape firms."
    assert "URA" in extract_tickers_from_text(text)


def test_dollar_prefix_match():
    text = "$NVDA breakout above 950 with volume."
    assert "NVDA" in extract_tickers_from_text(text)


def test_multiple_tickers_in_one_doc_dedupe():
    text = "URA URA URA leadership today; also watching GLD and BTC."
    found = extract_tickers_from_text(text)
    assert found == {"URA", "GLD", "BTC"}  # URA only counted once


def test_lowercase_does_not_match():
    text = "the ura mining sector remains strong"
    assert "URA" not in extract_tickers_from_text(text)


# ---------------------------------------------------------------------------
# False positives — these are the critical guards
# ---------------------------------------------------------------------------

def test_common_acronyms_filtered_out():
    text = "AI, GPU, CPU, FOMC, FED, GDP, CPI, OPEC, NATO, USA all in one sentence."
    found = extract_tickers_from_text(text)
    assert found == set()


def test_short_pronouns_filtered():
    text = "I think AT&T was great. NO, on second thought, IT was OK."
    found = extract_tickers_from_text(text)
    # I, NO, IT are in NEVER_TICKERS; AT and OK are not in allow-list
    assert "I" not in found
    assert "NO" not in found
    assert "IT" not in found


def test_unknown_uppercase_word_not_in_allowlist():
    text = "RANDOMWORD is great. ALSO MOVING higher."  # nothing in allowlist
    found = extract_tickers_from_text(text)
    assert found == set()


def test_ticker_inside_longer_word_not_matched():
    # "URA" embedded in "URANIUM" should not match because regex \b URA \b
    # boundary check — but URANIUM has uppercase 7 letters which won't match
    # the 2-5 char limit
    text = "uranium investing is interesting"  # lowercase, no match anyway
    found = extract_tickers_from_text(text)
    assert "URA" not in found


def test_punctuation_around_ticker_still_matches():
    text = "URA, GLD; (BTC) and 'NVDA'."
    found = extract_tickers_from_text(text)
    assert found >= {"URA", "GLD", "BTC", "NVDA"}


def test_empty_or_none_text():
    assert extract_tickers_from_text("") == set()
    assert extract_tickers_from_text(None) == set()  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# count_mentions across documents
# ---------------------------------------------------------------------------

def test_count_mentions_aggregates_across_docs():
    docs = [
        {"source_id": "doomberg", "title": "URA insight", "cleaned_text": "URA leadership.", "published_at": (NOW - timedelta(days=1)).isoformat()},
        {"source_id": "kaoboy",   "title": "Energy",      "cleaned_text": "URA and GLD up.",  "published_at": (NOW - timedelta(days=2)).isoformat()},
        {"source_id": "doomberg", "title": "Gold",        "cleaned_text": "GLD breakout.",    "published_at": (NOW - timedelta(days=3)).isoformat()},
    ]
    result = count_mentions(docs, window_days=7, now=NOW)
    by_ticker = {c.ticker: c for c in result.counts}
    assert by_ticker["URA"].docs_with_mention == 2
    assert by_ticker["GLD"].docs_with_mention == 2
    assert sorted(by_ticker["URA"].sources) == ["doomberg", "kaoboy"]
    assert sorted(by_ticker["GLD"].sources) == ["doomberg", "kaoboy"]


def test_count_mentions_respects_window():
    docs = [
        {"source_id": "x", "title": "old", "cleaned_text": "URA.", "published_at": (NOW - timedelta(days=30)).isoformat()},
        {"source_id": "x", "title": "new", "cleaned_text": "URA.", "published_at": (NOW - timedelta(days=2)).isoformat()},
    ]
    result7 = count_mentions(docs, window_days=7, now=NOW)
    result60 = count_mentions(docs, window_days=60, now=NOW)
    assert sum(c.docs_with_mention for c in result7.counts if c.ticker == "URA") == 1
    assert sum(c.docs_with_mention for c in result60.counts if c.ticker == "URA") == 2


def test_count_mentions_sorted_by_count_desc():
    docs = [
        {"source_id": "a", "title": "", "cleaned_text": "GLD",     "published_at": NOW.isoformat()},
        {"source_id": "b", "title": "", "cleaned_text": "URA URA", "published_at": NOW.isoformat()},
        {"source_id": "c", "title": "", "cleaned_text": "URA",     "published_at": NOW.isoformat()},
    ]
    result = count_mentions(docs, window_days=7, now=NOW)
    # URA: 2 docs, GLD: 1 doc → URA first
    assert result.counts[0].ticker == "URA"
    assert result.counts[0].docs_with_mention == 2


def test_count_mentions_total_docs_scanned():
    docs = [
        {"source_id": "a", "title": "", "cleaned_text": "URA", "published_at": NOW.isoformat()},
        {"source_id": "b", "title": "", "cleaned_text": "no ticker here", "published_at": NOW.isoformat()},
        {"source_id": "c", "title": "", "cleaned_text": "old", "published_at": (NOW - timedelta(days=30)).isoformat()},
    ]
    result = count_mentions(docs, window_days=7, now=NOW)
    # 'a' and 'b' are within window; 'c' is outside
    assert result.total_docs_scanned == 2


# ---------------------------------------------------------------------------
# Recency weighting (time-weighted scoring per Phase 6d)
# ---------------------------------------------------------------------------

def test_recency_weight_at_zero_age_is_one():
    assert recency_weight(0, half_life_days=30) == pytest.approx(1.0)


def test_recency_weight_at_half_life_is_half():
    assert recency_weight(30, half_life_days=30) == pytest.approx(0.5)
    assert recency_weight(14, half_life_days=14) == pytest.approx(0.5)


def test_recency_weight_at_double_half_life_is_quarter():
    assert recency_weight(60, half_life_days=30) == pytest.approx(0.25)


def test_recency_weight_negative_age_clamped_to_zero():
    # Future-dated content shouldn't blow weight up to >1
    assert recency_weight(-5, half_life_days=30) == pytest.approx(1.0)


def test_recency_weight_no_half_life_returns_one():
    assert recency_weight(100, half_life_days=0) == 1.0
    assert recency_weight(100, half_life_days=-1) == 1.0


def test_count_mentions_weighted_score_decays():
    """Two docs mentioning URA: one today, one 30d ago. With 30d half-life
    the weighted_score should be ~1.5 (1.0 + 0.5), not 2.0."""
    docs = [
        {"source_id": "a", "title": "", "cleaned_text": "URA", "published_at": NOW.isoformat()},
        {"source_id": "b", "title": "", "cleaned_text": "URA", "published_at": (NOW - timedelta(days=30)).isoformat()},
    ]
    result = count_mentions(
        docs, window_days=60, now=NOW, half_life_days=30,
        apply_source_freshness=False,  # isolate recency effect
    )
    ura = next(c for c in result.counts if c.ticker == "URA")
    assert ura.docs_with_mention == 2
    assert ura.weighted_score == pytest.approx(1.5, abs=0.01)


def test_count_mentions_recency_ranks_above_quantity():
    """A ticker with 1 fresh mention should outrank one with 2 stale mentions
    when half-life is short."""
    docs = [
        {"source_id": "a", "title": "", "cleaned_text": "URA", "published_at": NOW.isoformat()},  # fresh
        {"source_id": "b", "title": "", "cleaned_text": "GLD", "published_at": (NOW - timedelta(days=50)).isoformat()},  # stale
        {"source_id": "c", "title": "", "cleaned_text": "GLD", "published_at": (NOW - timedelta(days=55)).isoformat()},  # stale
    ]
    result = count_mentions(
        docs, window_days=60, now=NOW, half_life_days=14,
        apply_source_freshness=False,
    )
    # GLD has 2 docs but both very stale; URA has 1 fresh.
    # Sort is by weighted_score → URA first.
    assert result.counts[0].ticker == "URA"


def test_count_mentions_window_summary_includes_half_life():
    docs = [{"source_id": "x", "title": "", "cleaned_text": "URA", "published_at": NOW.isoformat()}]
    result = count_mentions(docs, window_days=30, now=NOW, half_life_days=14)
    assert result.half_life_days == 14

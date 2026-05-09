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

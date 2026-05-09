"""Tests for scoring/watchlist_resolver.py."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from macro_positioning.scoring.watchlist_resolver import resolve_watchlist


NOW = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)


def test_anchors_always_included_no_docs():
    """No docs, any regime: every anchor flows through with 'anchor' origin."""
    result = resolve_watchlist(framework_regime="transitional_chop", documents=None)
    tickers = {e.ticker for e in result.entries}
    # config/watchlist.json anchors must all be present
    for anchor in ("SPY", "URA", "GLD", "BTC", "QQQ", "TLT"):
        assert anchor in tickers, f"anchor {anchor} missing"
    # Each anchor specifically must list 'anchor' in its origins
    # (other tickers may join via theme or mention; only anchors guaranteed
    # to have 'anchor' origin)
    by_ticker = {e.ticker: e for e in result.entries}
    for anchor in ("SPY", "URA", "GLD", "BTC"):
        assert "anchor" in by_ticker[anchor].origins


def test_theme_tickers_join_when_regime_aligns():
    """commodity_led_inflation regime → uranium + PM + energy themes' tickers join."""
    result = resolve_watchlist(framework_regime="commodity_led_inflation", documents=None)
    tickers = {e.ticker for e in result.entries}
    # Uranium theme tickers (preferred_regime includes commodity_led_inflation)
    assert "URNM" in tickers
    assert "DNN" in tickers
    # PM theme tickers
    assert "GDX" in tickers
    # Should have origin like "theme:uranium" or "theme:precious_metals"
    urnm = next(e for e in result.entries if e.ticker == "URNM")
    assert any(o.startswith("theme:") for o in urnm.origins)


def test_anchor_takes_precedence_in_origins_order():
    """A ticker that is BOTH an anchor AND in a theme should list anchor first."""
    result = resolve_watchlist(framework_regime="commodity_led_inflation", documents=None)
    ura = next(e for e in result.entries if e.ticker == "URA")
    # URA is an anchor; it's also referenced in uranium theme — both origins present
    assert "anchor" in ura.origins
    # First-added wins for origins order; anchors load first → "anchor" should be first
    assert ura.origins[0] == "anchor"


def test_mention_extraction_promotes_unanchored_ticker():
    """When mentions are present, top tickers above threshold join the watchlist."""
    docs = [
        {"source_id": s, "title": "", "cleaned_text": "NVDA leadership.", "published_at": (NOW - timedelta(days=i)).isoformat()}
        for i, s in enumerate(["doomberg", "kaoboy", "stockunlocked", "realvision", "qtr_fringe"])
    ]
    # NVDA is in allow-list (tech_ai theme) but tech_ai theme prefers risk_on_expansion
    # NOT commodity_led_inflation, so it WON'T join via theme stream.
    # It SHOULD join via mention stream (5 docs, above min=3).
    result = resolve_watchlist(
        framework_regime="commodity_led_inflation",
        documents=docs,
        mention_min_count=3,
    )
    nvda = next((e for e in result.entries if e.ticker == "NVDA"), None)
    assert nvda is not None
    # Should have a "mentions:..." origin
    assert any(o.startswith("mentions:") for o in nvda.origins)


def test_mention_below_min_count_does_not_promote():
    """Tickers mentioned only once shouldn't join the list."""
    docs = [
        {"source_id": "doomberg", "title": "", "cleaned_text": "ARKK is interesting", "published_at": NOW.isoformat()},
    ]
    result = resolve_watchlist(
        framework_regime="commodity_led_inflation",
        documents=docs,
        mention_min_count=3,  # ARKK has only 1 mention
    )
    arkk = next((e for e in result.entries if e.ticker == "ARKK"), None)
    assert arkk is None


def test_resolved_watchlist_includes_mention_summary():
    docs = [
        {"source_id": s, "title": "", "cleaned_text": "URA URA URA", "published_at": NOW.isoformat()}
        for s in ["doomberg", "kaoboy", "stockunlocked", "realvision"]
    ]
    result = resolve_watchlist(
        framework_regime="commodity_led_inflation",
        documents=docs,
        mention_windows=(7,),
        mention_min_count=2,
    )
    assert 7 in result.mention_summary
    summary = result.mention_summary[7]
    assert summary["total_docs_scanned"] == 4
    assert summary["tickers_above_threshold"] >= 1
    assert any(t["ticker"] == "URA" for t in summary["top_5"])


def test_total_count_matches_entries():
    result = resolve_watchlist(framework_regime="risk_on_expansion", documents=None)
    assert result.total_count == len(result.entries)

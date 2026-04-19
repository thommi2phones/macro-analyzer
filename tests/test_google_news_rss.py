"""Tests for the Google News RSS connector (feed fetch is monkeypatched)."""
from __future__ import annotations

from macro_positioning.ingestion import google_news_rss as gn

SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Google News</title>
    <item>
      <title>Inflation prints hotter than expected</title>
      <link>https://news.google.com/articles/inflation-1</link>
      <pubDate>Mon, 05 Jan 2026 12:00:00 GMT</pubDate>
      <description>Core CPI came in above consensus for the third month.</description>
    </item>
    <item>
      <title>Fed officials signal patience</title>
      <link>https://news.google.com/articles/fed-1</link>
      <pubDate>Tue, 06 Jan 2026 09:00:00 GMT</pubDate>
      <description>Policymakers stress data dependence.</description>
    </item>
  </channel>
</rss>
"""


def test_build_rss_url_quotes_query():
    url = gn.build_rss_url("inflation CPI PCE")
    assert "news.google.com/rss/search" in url
    assert "q=inflation%20CPI%20PCE" in url
    assert "hl=en-US" in url


def test_fetch_query_annotates_tags(monkeypatch):
    monkeypatch.setattr(gn, "fetch_feed", lambda url, timeout=20.0: SAMPLE_XML)
    docs = gn.fetch_query("inflation", tag_topic="inflation")
    assert len(docs) == 2
    assert all(d.source_id == "google_news" for d in docs)
    assert all("google_news" in d.tags and "inflation" in d.tags for d in docs)
    assert docs[0].url == "https://news.google.com/articles/inflation-1"


def test_fetch_query_without_topic_has_single_tag(monkeypatch):
    monkeypatch.setattr(gn, "fetch_feed", lambda url, timeout=20.0: SAMPLE_XML)
    docs = gn.fetch_query("random query")
    assert all(d.tags == ["google_news"] for d in docs)


def test_fetch_topic_resolves_macro_query(monkeypatch):
    captured: dict = {}
    def fake_fetch(url, timeout=20.0):
        captured["url"] = url
        return SAMPLE_XML
    monkeypatch.setattr(gn, "fetch_feed", fake_fetch)
    docs = gn.fetch_topic("rates", max_items=5)
    assert len(docs) == 2
    # Query string for "rates" is the multi-word Fed/Treasury string
    assert "Federal%20Reserve" in captured["url"]


def test_fetch_all_macro_topics_iterates(monkeypatch):
    call_count = {"n": 0}
    def fake_fetch(url, timeout=20.0):
        call_count["n"] += 1
        return SAMPLE_XML
    monkeypatch.setattr(gn, "fetch_feed", fake_fetch)
    docs = gn.fetch_all_macro_topics(max_items_per_topic=2)
    assert call_count["n"] == len(gn.MACRO_QUERIES)
    # Each call yields 2 items
    assert len(docs) == 2 * len(gn.MACRO_QUERIES)


def test_fetch_all_macro_topics_handles_failure(monkeypatch):
    def boom(url, timeout=20.0):
        raise RuntimeError("network down")
    monkeypatch.setattr(gn, "fetch_feed", boom)
    # Should not raise; returns empty list with warnings logged
    docs = gn.fetch_all_macro_topics()
    assert docs == []

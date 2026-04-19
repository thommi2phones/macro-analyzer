"""Tests for the RSS / Atom connector parser."""
from __future__ import annotations

from macro_positioning.ingestion.rss_connector import parse_feed

RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"
     xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel>
    <title>Example Macro Feed</title>
    <item>
      <title>Duration works in a slowing economy</title>
      <link>https://example.com/duration-slowing</link>
      <pubDate>Mon, 03 Mar 2026 12:00:00 GMT</pubDate>
      <dc:creator>Example Author</dc:creator>
      <content:encoded><![CDATA[
        <p>Real yields are falling. <strong>We like duration here.</strong></p>
        <script>alert("no")</script>
      ]]></content:encoded>
    </item>
    <item>
      <title>No body item</title>
      <link>https://example.com/nobody</link>
      <pubDate>Mon, 03 Mar 2026 12:00:00 GMT</pubDate>
      <description></description>
    </item>
  </channel>
</rss>
"""

ATOM_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Macro Feed</title>
  <entry>
    <title>Dollar fatigue into quarter end</title>
    <link href="https://example.com/dxy"/>
    <published>2026-03-01T10:00:00Z</published>
    <author><name>Atom Author</name></author>
    <summary>We think the dollar is rolling over as growth stabilizes.</summary>
  </entry>
</feed>
"""


class TestParseFeed:
    def test_parses_rss_item(self):
        docs = parse_feed(RSS_SAMPLE, source_id="rss_test")
        assert len(docs) == 1  # the bodyless item should be skipped
        doc = docs[0]
        assert doc.title == "Duration works in a slowing economy"
        assert doc.url == "https://example.com/duration-slowing"
        assert doc.author == "Example Author"
        assert "duration" in doc.raw_text.lower()
        assert "alert" not in doc.raw_text  # script stripped
        assert doc.published_at.year == 2026

    def test_parses_atom_entry(self):
        docs = parse_feed(ATOM_SAMPLE, source_id="atom_test")
        assert len(docs) == 1
        doc = docs[0]
        assert doc.title == "Dollar fatigue into quarter end"
        assert doc.url == "https://example.com/dxy"
        assert doc.author == "Atom Author"
        assert "dollar" in doc.raw_text.lower()

    def test_empty_xml_returns_empty(self):
        assert parse_feed("", source_id="x") == []

    def test_malformed_xml_returns_empty(self):
        assert parse_feed("<rss><<broken", source_id="x") == []

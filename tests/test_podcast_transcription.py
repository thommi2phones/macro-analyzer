"""End-to-end test: podcast RSS + transcription integration.

Mocks the RSS fetch and the transcribe_audio_url() call to verify that
fetch_podcast(transcribe=True) correctly combines show notes + transcript
and tags documents appropriately.
"""
from __future__ import annotations

import pytest

from macro_positioning.ingestion import podcast_rss


SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>Test Podcast</title>
    <item>
      <title>Ep 1: Macro Outlook</title>
      <link>https://example.com/ep1</link>
      <guid>ep-1-guid</guid>
      <pubDate>Fri, 18 Apr 2026 10:00:00 +0000</pubDate>
      <description>Macro outlook episode covering inflation, Fed policy decisions, the dollar index, and implications for risk assets.</description>
      <enclosure url="https://cdn.example.com/ep1.mp3" type="audio/mpeg" length="0"/>
      <itunes:duration>3600</itunes:duration>
    </item>
    <item>
      <title>Ep 2: Crypto</title>
      <link>https://example.com/ep2</link>
      <pubDate>Thu, 17 Apr 2026 10:00:00 +0000</pubDate>
      <description>Deep dive on Bitcoin spot ETF flows, Ethereum staking economics, and broader crypto market structure.</description>
      <enclosure url="https://cdn.example.com/ep2.mp3" type="audio/mpeg"/>
    </item>
  </channel>
</rss>
"""


class _FakeHttpxResponse:
    def __init__(self, text: str, status: int = 200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def get(self, url, **kwargs):
        return _FakeHttpxResponse(SAMPLE_FEED)


def _register_fake_source(monkeypatch):
    """Ensure there's a test source registered for fetch_podcast() lookup."""
    test_source = podcast_rss.PodcastSource(
        source_id="test_podcast",
        name="Test Podcast",
        rss_url="https://cdn.example.com/feed.xml",
        priority="core",
        tags=["test"],
    )
    new_sources = list(podcast_rss.PODCAST_SOURCES) + [test_source]
    monkeypatch.setattr(podcast_rss, "PODCAST_SOURCES", new_sources)


def test_show_notes_only_path(monkeypatch):
    """transcribe=False returns show-notes-only docs with the right tags."""
    _register_fake_source(monkeypatch)
    monkeypatch.setattr(podcast_rss.httpx, "Client", _FakeClient)

    docs = podcast_rss.fetch_podcast("test_podcast", max_items=5, transcribe=False)
    assert len(docs) == 2
    for d in docs:
        assert "show_notes_only" in d.tags
        assert "with_transcript" not in d.tags
        assert "FULL TRANSCRIPT" not in d.raw_text
        assert "podcast" in d.tags


def test_transcription_combines_show_notes_and_transcript(monkeypatch):
    """transcribe=True → raw_text has both sections, tagged with_transcript."""
    _register_fake_source(monkeypatch)
    monkeypatch.setattr(podcast_rss.httpx, "Client", _FakeClient)

    # Mock the transcription call the lazy import inside fetch_podcast will do
    from macro_positioning.brain import transcription as trans

    def fake_transcribe(audio_url, **kwargs):
        return trans.TranscriptionResult(
            text=f"[transcript for {audio_url}]",
            model="gemini-2.5-pro",
            latency_ms=1234.0,
        )

    monkeypatch.setattr(trans, "transcribe_audio_url", fake_transcribe)

    docs = podcast_rss.fetch_podcast("test_podcast", max_items=5, transcribe=True)
    assert len(docs) == 2
    for d in docs:
        assert "with_transcript" in d.tags
        assert "transcription_failed" not in d.tags
        assert "FULL TRANSCRIPT" in d.raw_text
        assert "[transcript for https://cdn.example.com/ep" in d.raw_text
        # Show notes still present
        assert ("inflation" in d.raw_text) or ("Bitcoin" in d.raw_text)


def test_transcription_failure_falls_back_to_show_notes(monkeypatch):
    """If transcribe_audio_url raises, episode still saved with show-notes only."""
    _register_fake_source(monkeypatch)
    monkeypatch.setattr(podcast_rss.httpx, "Client", _FakeClient)

    from macro_positioning.brain import transcription as trans

    def boom(audio_url, **kwargs):
        raise RuntimeError("N8N audio webhook down")

    monkeypatch.setattr(trans, "transcribe_audio_url", boom)

    docs = podcast_rss.fetch_podcast("test_podcast", max_items=5, transcribe=True)
    assert len(docs) == 2
    for d in docs:
        assert "transcription_failed" in d.tags
        assert "with_transcript" not in d.tags
        assert "FULL TRANSCRIPT" not in d.raw_text


def test_mp3_url_extracted_from_enclosure(monkeypatch):
    """Verify the new _parse_episode correctly identifies MP3 enclosure URLs."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(SAMPLE_FEED)
    item = root.find("channel").find("item")
    ep = podcast_rss._parse_episode(item)
    assert ep is not None
    assert ep.mp3_url == "https://cdn.example.com/ep1.mp3"
    assert ep.url == "https://example.com/ep1"  # link takes priority over mp3


def test_mp3_url_none_when_no_audio_enclosure(monkeypatch):
    """Video enclosures or missing enclosures should NOT surface as mp3_url."""
    import xml.etree.ElementTree as ET
    xml = """<item>
        <title>Test</title>
        <pubDate>Fri, 18 Apr 2026 10:00:00 +0000</pubDate>
        <description>Notes</description>
        <enclosure url="https://cdn.example.com/video.mp4" type="video/mp4"/>
    </item>"""
    item = ET.fromstring(xml)
    ep = podcast_rss._parse_episode(item)
    assert ep.mp3_url is None

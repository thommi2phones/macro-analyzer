"""Substack ingest module: feed config loading + source_id namespacing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from macro_positioning.core.settings import settings
from macro_positioning.ingestion import substack


@pytest.fixture
def base_dir(tmp_path: Path, monkeypatch):
    (tmp_path / "config").mkdir()
    monkeypatch.setattr(settings, "base_dir", tmp_path)
    return tmp_path


def test_load_feeds_missing_file_returns_empty(base_dir):
    assert substack.load_feeds() == []


def test_load_feeds_malformed_json_returns_empty(base_dir):
    (base_dir / "config" / "substack_feeds.json").write_text("not json {{")
    assert substack.load_feeds() == []


def test_load_feeds_happy_path(base_dir):
    (base_dir / "config" / "substack_feeds.json").write_text(json.dumps({
        "feeds": [
            {"slug": "doomberg",
             "url": "https://doomberg.substack.com/feed",
             "tags": ["energy"]},
            {"slug": "themarketear",
             "url": "https://themarketear.substack.com/feed"},
        ]
    }))
    feeds = substack.load_feeds()
    assert len(feeds) == 2
    assert feeds[0]["slug"] == "doomberg"
    assert feeds[1].get("tags") is None


def test_fetch_feed_entries_namespace(monkeypatch):
    """source_id must be 'substack:{slug}' — never bare 'substack'.
    Otherwise data_health + signal attribution lose per-publication
    granularity.
    """
    from macro_positioning.core.models import RawDocument

    def fake_fetch(url: str) -> bytes:
        return b"<rss></rss>"   # parse_feed will return []

    def fake_parse(xml, source_id, max_items):
        # Return one canned document so we can inspect the source_id
        # propagated by the connector.
        return [RawDocument(
            source_id=source_id,
            title="t",
            url="https://example.com/x",
            published_at="2026-06-04T00:00:00",
            raw_text="x",
            tags=[],
        )]

    monkeypatch.setattr(substack, "fetch_feed", fake_fetch)
    monkeypatch.setattr(substack, "parse_feed", fake_parse)

    docs = substack.fetch_feed_entries(
        slug="doomberg",
        url="https://doomberg.substack.com/feed",
        max_items=5,
        extra_tags=["energy", "macro"],
    )
    assert docs and docs[0].source_id == "substack:doomberg"
    assert "substack" in docs[0].tags
    assert "doomberg" in docs[0].tags
    assert "energy" in docs[0].tags


def test_fetch_all_iterates_and_errors_isolated(monkeypatch, base_dir):
    (base_dir / "config" / "substack_feeds.json").write_text(json.dumps({
        "feeds": [
            {"slug": "good", "url": "https://good.substack.com/feed"},
            {"slug": "bad", "url": "https://bad.substack.com/feed"},
        ]
    }))

    from macro_positioning.core.models import RawDocument

    def fake_entries(slug, url, max_items=20, extra_tags=None):
        if slug == "bad":
            raise RuntimeError("simulated network error")
        return [RawDocument(
            source_id=f"substack:{slug}",
            title="ok", url="https://x.test/", published_at="2026-06-04",
            raw_text="x", tags=[],
        )]

    monkeypatch.setattr(substack, "fetch_feed_entries", fake_entries)
    out = substack.fetch_all()
    assert len(out) == 1
    assert out[0].source_id == "substack:good"

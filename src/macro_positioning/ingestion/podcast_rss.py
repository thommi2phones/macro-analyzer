"""Podcast RSS connector — pulls episode show notes + metadata.

Works with standard podcast RSS feeds (iTunes/Megaphone/Libsyn/Anchor/etc.)
We extract show notes (`<description>`, `<content:encoded>`, `<itunes:summary>`)
which usually contain rich text on what was discussed — often enough signal
for the Brain without needing audio transcription.

Later: can add Whisper transcription of the `<enclosure url="...">` MP3 for
full transcript analysis. For now, show notes are the ingestion path.

Usage:
    from macro_positioning.ingestion.podcast_rss import (
        fetch_podcast, fetch_all_podcasts, PODCAST_SOURCES,
    )
    docs = fetch_podcast("wolf_of_all_streets")
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from xml.etree import ElementTree as ET

import httpx

from macro_positioning.core.models import RawDocument

logger = logging.getLogger(__name__)


@dataclass
class PodcastSource:
    """A podcast we follow by RSS."""
    source_id: str
    name: str
    rss_url: str
    host: str | None = None
    market_focus: list[str] = field(default_factory=list)
    priority: str = "secondary"
    tags: list[str] = field(default_factory=list)
    notes: str = ""


# ─── Configured podcasts ───────────────────────────────────────────────────

PODCAST_SOURCES: list[PodcastSource] = [
    PodcastSource(
        source_id="wolf_of_all_streets",
        name="The Wolf of All Streets",
        rss_url="https://feeds.megaphone.fm/wolfofallstreets",
        host="Scott Melker",
        market_focus=["crypto", "macro", "equities"],
        priority="core",
        tags=["crypto", "macro", "podcast"],
    ),
]


# ─── RSS parsing ────────────────────────────────────────────────────────────

# Namespaces common in podcast feeds
NS = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
    "atom": "http://www.w3.org/2005/Atom",
    "dc": "http://purl.org/dc/elements/1.1/",
}


def _parse_pubdate(text: str | None) -> datetime:
    """Best-effort RFC-822 podcast date parse."""
    if not text:
        return datetime.now(UTC)
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%d %b %Y %H:%M:%S %z",
    ):
        try:
            return datetime.strptime(text.strip(), fmt).astimezone(UTC)
        except ValueError:
            continue
    return datetime.now(UTC)


def _strip_html(html: str) -> str:
    """Quick HTML strip for show notes — uses BS4 if available."""
    if not html:
        return ""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
    except ImportError:
        text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n", "\n\n", text)
    return text.strip()


def _find_text(item: ET.Element, *candidates: str) -> str:
    """Return the first non-empty child text from the candidate tags."""
    for c in candidates:
        el = item.find(c, NS)
        if el is not None and el.text:
            return el.text
    return ""


def parse_podcast_feed(
    xml: str,
    source_id: str,
    max_items: int = 20,
    tags: list[str] | None = None,
) -> list[RawDocument]:
    """Parse a podcast RSS feed into RawDocument records for each episode."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        logger.warning("Podcast XML parse failed for %s: %s", source_id, e)
        return []

    channel = root.find("channel")
    if channel is None:
        return []

    docs: list[RawDocument] = []
    items = channel.findall("item")[:max_items]

    for item in items:
        title = (_find_text(item, "title") or "").strip()
        if not title:
            continue

        # Show notes: prefer content:encoded, then description, then itunes:summary
        raw_notes = (
            _find_text(item, "{http://purl.org/rss/1.0/modules/content/}encoded")
            or _find_text(item, "description")
            or _find_text(item, "{http://www.itunes.com/dtds/podcast-1.0.dtd}summary")
        )
        show_notes_text = _strip_html(raw_notes)

        # Episode URL: prefer <link>, fallback to <guid>, then <enclosure url=...>
        link_el = item.find("link")
        guid_el = item.find("guid")
        enclosure = item.find("enclosure")
        url = (
            (link_el.text.strip() if link_el is not None and link_el.text else None)
            or (guid_el.text.strip() if guid_el is not None and guid_el.text else None)
            or (enclosure.get("url") if enclosure is not None else None)
        )

        pub_date = _parse_pubdate(_find_text(item, "pubDate"))

        # Duration / episode number enrich the text body for brain context
        duration = _find_text(item, "{http://www.itunes.com/dtds/podcast-1.0.dtd}duration")
        episode = _find_text(item, "{http://www.itunes.com/dtds/podcast-1.0.dtd}episode")
        season = _find_text(item, "{http://www.itunes.com/dtds/podcast-1.0.dtd}season")

        prefix_parts = []
        if season:
            prefix_parts.append(f"Season {season}")
        if episode:
            prefix_parts.append(f"Episode {episode}")
        if duration:
            prefix_parts.append(f"Duration {duration}")
        prefix = (" | ".join(prefix_parts) + "\n") if prefix_parts else ""

        raw_text = prefix + show_notes_text
        if len(raw_text) < 50:
            continue

        doc_id = hashlib.sha1(f"{source_id}|{url or title}|{pub_date.isoformat()}".encode()).hexdigest()[:16]
        docs.append(RawDocument(
            source_id=source_id,
            title=title,
            url=url,
            published_at=pub_date,
            author=None,
            content_type="transcript",  # show notes treated as lightweight transcript
            raw_text=raw_text,
            tags=list(tags) if tags else ["podcast"],
        ))

    return docs


# ─── Public API ─────────────────────────────────────────────────────────────

def fetch_podcast(source_id: str, max_items: int = 20) -> list[RawDocument]:
    """Fetch one configured podcast's recent episodes as RawDocuments."""
    source = next((p for p in PODCAST_SOURCES if p.source_id == source_id), None)
    if source is None:
        raise ValueError(f"Unknown podcast source_id: {source_id!r}")

    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            r = client.get(source.rss_url)
            r.raise_for_status()
            xml = r.text
    except Exception as e:
        logger.warning("Failed to fetch podcast feed %s: %s", source.rss_url, e)
        return []

    tags = ["podcast"] + list(source.tags)
    docs = parse_podcast_feed(xml, source_id=source_id, max_items=max_items, tags=tags)
    logger.info("Podcast %s -> %d episodes", source_id, len(docs))
    return docs


def fetch_all_podcasts(max_items_per_podcast: int = 10) -> list[RawDocument]:
    """Fetch every configured podcast in one pass."""
    out: list[RawDocument] = []
    for p in PODCAST_SOURCES:
        try:
            out.extend(fetch_podcast(p.source_id, max_items=max_items_per_podcast))
        except Exception as e:
            logger.warning("Podcast fetch failed %s: %s", p.source_id, e)
    return out

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
    # ═══ CORE — full transcription via Gemini/N8N ═══
    PodcastSource(
        source_id="forward_guidance",
        name="Forward Guidance",
        rss_url="https://feeds.megaphone.fm/forwardguidance",
        host="Jack Farley",
        market_focus=["macro", "rates", "liquidity", "fx"],
        priority="core",
        tags=["macro", "rates", "podcast"],
        notes="User favorite — full transcription enabled.",
    ),
    PodcastSource(
        source_id="wolf_of_all_streets",
        name="The Wolf of All Streets",
        rss_url="https://feeds.megaphone.fm/wolfofallstreets",
        host="Scott Melker",
        market_focus=["crypto", "macro", "equities"],
        priority="core",
        tags=["crypto", "macro", "podcast"],
    ),
    PodcastSource(
        source_id="real_vision_journeyman",
        name="Real Vision: The Journey Man",
        rss_url="https://feeds.megaphone.fm/realvisioncryptopodcast",
        host="Raoul Pal",
        market_focus=["macro", "crypto", "equities"],
        priority="core",
        tags=["macro", "crypto", "podcast"],
    ),

    # ═══ SECONDARY — show notes only ═══
    PodcastSource(
        source_id="moonshots_diamandis",
        name="Moonshots with Peter Diamandis",
        rss_url="https://feeds.megaphone.fm/DVVTS2890392624",
        host="Peter Diamandis",
        market_focus=["ai", "tech", "future_trends"],
        priority="secondary",
        tags=["ai", "podcast"],
        notes="Light macro influence — AI/futurist focus. Show notes only.",
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


@dataclass
class ParsedEpisode:
    """Intermediate episode record with all the metadata needed to decide
    whether to transcribe. parse_podcast_feed_raw returns these, then
    fetch_podcast() decides whether to call transcribe_audio_url() before
    turning them into RawDocuments.
    """
    title: str
    url: str | None             # episode page URL (for link-back / dedup)
    mp3_url: str | None         # MP3 enclosure URL (for transcription)
    pub_date: datetime
    show_notes_text: str
    episode_prefix: str         # "Season X | Episode Y | Duration Z"


def _parse_episode(item: ET.Element) -> ParsedEpisode | None:
    """Extract a ParsedEpisode from one <item>. Returns None if title missing."""
    title = (_find_text(item, "title") or "").strip()
    if not title:
        return None

    # Show notes: prefer content:encoded, then description, then itunes:summary
    raw_notes = (
        _find_text(item, "{http://purl.org/rss/1.0/modules/content/}encoded")
        or _find_text(item, "description")
        or _find_text(item, "{http://www.itunes.com/dtds/podcast-1.0.dtd}summary")
    )
    show_notes_text = _strip_html(raw_notes)

    # Episode page URL: prefer <link>, fallback to <guid>
    link_el = item.find("link")
    guid_el = item.find("guid")
    url = (
        (link_el.text.strip() if link_el is not None and link_el.text else None)
        or (guid_el.text.strip() if guid_el is not None and guid_el.text else None)
    )

    # MP3 URL (separately from the episode URL — needed for transcription)
    enclosure = item.find("enclosure")
    mp3_url = None
    if enclosure is not None:
        enc_type = (enclosure.get("type") or "").lower()
        enc_url = enclosure.get("url")
        if enc_url and ("audio" in enc_type or enc_url.lower().endswith(".mp3")):
            mp3_url = enc_url
    # Fall back to enclosure URL as the episode URL if neither link nor guid
    if not url and mp3_url:
        url = mp3_url

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
    episode_prefix = (" | ".join(prefix_parts) + "\n") if prefix_parts else ""

    return ParsedEpisode(
        title=title,
        url=url,
        mp3_url=mp3_url,
        pub_date=pub_date,
        show_notes_text=show_notes_text,
        episode_prefix=episode_prefix,
    )


def parse_podcast_feed(
    xml: str,
    source_id: str,
    max_items: int = 20,
    tags: list[str] | None = None,
) -> list[RawDocument]:
    """Parse a podcast RSS feed into RawDocument records (show notes only).

    For the transcribed path, use fetch_podcast(transcribe=True) instead.
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        logger.warning("Podcast XML parse failed for %s: %s", source_id, e)
        return []

    channel = root.find("channel")
    if channel is None:
        return []

    docs: list[RawDocument] = []
    for item in channel.findall("item")[:max_items]:
        ep = _parse_episode(item)
        if ep is None:
            continue
        raw_text = ep.episode_prefix + ep.show_notes_text
        if len(raw_text) < 50:
            continue
        docs.append(_build_document(
            source_id=source_id,
            episode=ep,
            raw_text=raw_text,
            tags=list(tags) if tags else ["podcast"],
            extra_tags=["show_notes_only"],
        ))
    return docs


def _build_document(
    source_id: str,
    episode: ParsedEpisode,
    raw_text: str,
    tags: list[str],
    extra_tags: list[str] | None = None,
) -> RawDocument:
    """Compose a RawDocument from a parsed episode + text + tags."""
    merged_tags = list(tags)
    if extra_tags:
        for t in extra_tags:
            if t not in merged_tags:
                merged_tags.append(t)
    return RawDocument(
        source_id=source_id,
        title=episode.title,
        url=episode.url,
        published_at=episode.pub_date,
        author=None,
        content_type="transcript",
        raw_text=raw_text,
        tags=merged_tags,
    )


# ─── Public API ─────────────────────────────────────────────────────────────

def fetch_podcast(
    source_id: str,
    max_items: int = 20,
    transcribe: bool = False,
) -> list[RawDocument]:
    """Fetch one configured podcast's recent episodes as RawDocuments.

    Args:
        source_id: Configured PodcastSource ID (e.g. "forward_guidance")
        max_items: Max episodes to return
        transcribe: If True, download each episode's MP3 and transcribe via
            the N8N audio webhook, combining show notes + transcript into
            raw_text. If transcription fails for an episode, falls back to
            show-notes-only for that episode (tagged transcription_failed).
    """
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

    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        logger.warning("Podcast XML parse failed for %s: %s", source_id, e)
        return []
    channel = root.find("channel")
    if channel is None:
        return []

    base_tags = ["podcast"] + list(source.tags)
    docs: list[RawDocument] = []

    for item in channel.findall("item")[:max_items]:
        ep = _parse_episode(item)
        if ep is None:
            continue

        base_body = ep.episode_prefix + ep.show_notes_text
        if len(base_body) < 50 and not (transcribe and ep.mp3_url):
            # No show notes AND no audio to transcribe → skip
            continue

        if transcribe and ep.mp3_url:
            # Lazy import so tests / show-notes-only paths don't require it
            from macro_positioning.brain.transcription import transcribe_audio_url

            try:
                result = transcribe_audio_url(ep.mp3_url)
                combined = (
                    f"{base_body}\n\n"
                    f"=== FULL TRANSCRIPT ===\n\n"
                    f"{result.text.strip()}"
                )
                docs.append(_build_document(
                    source_id=source_id,
                    episode=ep,
                    raw_text=combined,
                    tags=base_tags,
                    extra_tags=["with_transcript"],
                ))
                continue
            except Exception as e:
                logger.warning(
                    "Transcription failed for %s (%s) — falling back to show notes: %s",
                    source_id, ep.title[:60], e,
                )
                extra = ["transcription_failed"]
        else:
            extra = ["show_notes_only"]

        if len(base_body) < 50:
            continue
        docs.append(_build_document(
            source_id=source_id,
            episode=ep,
            raw_text=base_body,
            tags=base_tags,
            extra_tags=extra,
        ))

    logger.info("Podcast %s -> %d episodes (transcribe=%s)", source_id, len(docs), transcribe)
    return docs


def fetch_all_podcasts(
    max_items_per_podcast: int = 10,
    transcribe_core: bool = False,
) -> list[RawDocument]:
    """Fetch every configured podcast in one pass.

    If transcribe_core=True, core-tier podcasts get full transcription;
    secondary/experimental tiers stay show-notes-only.
    """
    out: list[RawDocument] = []
    for p in PODCAST_SOURCES:
        do_transcribe = transcribe_core and p.priority == "core"
        try:
            out.extend(fetch_podcast(
                p.source_id,
                max_items=max_items_per_podcast,
                transcribe=do_transcribe,
            ))
        except Exception as e:
            logger.warning("Podcast fetch failed %s: %s", p.source_id, e)
    return out

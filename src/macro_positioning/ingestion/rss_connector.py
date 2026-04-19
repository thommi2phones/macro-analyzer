"""Lightweight RSS / Atom feed connector.

No feedparser dependency - we parse a subset of feed formats using only
stdlib + the existing httpx/bs4 dependencies. Good enough to ingest
newsletter RSS feeds, Substack feeds, and most blog feeds.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

import httpx
from bs4 import BeautifulSoup

from macro_positioning.core.models import RawDocument

logger = logging.getLogger(__name__)

# XML namespaces we'll see in the wild
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
}


def fetch_feed(url: str, timeout: float = 20.0) -> str:
    """Fetch raw feed XML. Returns empty string on failure."""
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(url, headers={"User-Agent": "MacroPositioningBot/0.1"})
            response.raise_for_status()
            return response.text
    except Exception:
        logger.warning("Failed to fetch RSS feed %s", url, exc_info=True)
        return ""


def parse_feed(xml_text: str, source_id: str, max_items: int = 25) -> list[RawDocument]:
    """Parse RSS 2.0 or Atom feed text into RawDocuments."""
    if not xml_text.strip():
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        logger.warning("Could not parse feed XML for source_id=%s", source_id)
        return []

    documents: list[RawDocument] = []

    # RSS 2.0: <rss><channel><item>
    for item in root.iter("item"):
        doc = _parse_rss_item(item, source_id)
        if doc:
            documents.append(doc)
        if len(documents) >= max_items:
            return documents

    # Atom: <feed><entry>
    for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
        doc = _parse_atom_entry(entry, source_id)
        if doc:
            documents.append(doc)
        if len(documents) >= max_items:
            break

    return documents


def _text_of(element: ET.Element | None) -> str:
    if element is None or element.text is None:
        return ""
    return element.text.strip()


def _clean_html(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "aside", "footer"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    return re.sub(r"\s+", " ", text).strip()


def _parse_date(raw: str) -> datetime:
    raw = raw.strip() if raw else ""
    if not raw:
        return datetime.now(timezone.utc)
    # Try RFC-2822 first (RSS)
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass
    # ISO 8601 (Atom)
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


def _parse_rss_item(item: ET.Element, source_id: str) -> RawDocument | None:
    title = _text_of(item.find("title"))
    link = _text_of(item.find("link"))
    pub_date = _parse_date(_text_of(item.find("pubDate")))
    author = _text_of(item.find("author")) or _text_of(item.find(f"{{{NS['dc']}}}creator"))
    description = _text_of(item.find("description"))
    content_encoded = _text_of(item.find(f"{{{NS['content']}}}encoded"))
    body_html = content_encoded or description
    body = _clean_html(body_html)
    if not title or not body:
        return None
    return RawDocument(
        source_id=source_id,
        title=title,
        url=link or None,
        published_at=pub_date,
        author=author or None,
        content_type="article",
        raw_text=body,
        tags=[],
    )


def _parse_atom_entry(entry: ET.Element, source_id: str) -> RawDocument | None:
    title = _text_of(entry.find(f"{{{NS['atom']}}}title"))
    link_el = entry.find(f"{{{NS['atom']}}}link")
    link = link_el.get("href") if link_el is not None else None
    published = _parse_date(
        _text_of(entry.find(f"{{{NS['atom']}}}published"))
        or _text_of(entry.find(f"{{{NS['atom']}}}updated"))
    )
    author_el = entry.find(f"{{{NS['atom']}}}author")
    author = _text_of(author_el.find(f"{{{NS['atom']}}}name")) if author_el is not None else ""
    content_html = (
        _text_of(entry.find(f"{{{NS['atom']}}}content"))
        or _text_of(entry.find(f"{{{NS['atom']}}}summary"))
    )
    body = _clean_html(content_html)
    if not title or not body:
        return None
    return RawDocument(
        source_id=source_id,
        title=title,
        url=link,
        published_at=published,
        author=author or None,
        content_type="article",
        raw_text=body,
        tags=[],
    )


def ingest_feeds(
    feeds: list[tuple[str, str]], max_items_per_feed: int = 20
) -> list[RawDocument]:
    """Convenience: fetch + parse a list of (source_id, url) pairs."""
    documents: list[RawDocument] = []
    for source_id, url in feeds:
        xml = fetch_feed(url)
        parsed = parse_feed(xml, source_id, max_items=max_items_per_feed)
        logger.info("RSS %s -> %d items", source_id, len(parsed))
        documents.extend(parsed)
    return documents

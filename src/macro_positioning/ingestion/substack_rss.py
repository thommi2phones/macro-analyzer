"""Substack RSS connector — pull public posts without email.

Every Substack publication exposes a public RSS feed at
    https://<slug>.substack.com/feed

This connector pulls those feeds so we pick up:
  - Public posts from pubs we don't subscribe to
  - Anything missed by Gmail (filtered/archived/spam)
  - Coverage from free-tier pubs where paid email delivery is inconsistent

Works alongside the Gmail path — documents are deduped at the DB layer by
(source_id, url) so running both connectors is safe.
"""

from __future__ import annotations

import logging

from macro_positioning.core.models import RawDocument
from macro_positioning.ingestion.gmail_connector import NEWSLETTER_SOURCES
from macro_positioning.ingestion.rss_connector import fetch_feed, parse_feed

logger = logging.getLogger(__name__)


# Slug mapping for known substack sources — derived from their sender_email.
# e.g. `doomberg@substack.com` → slug `doomberg` → feed at doomberg.substack.com/feed
def substack_slug(source) -> str | None:
    """Return the Substack slug if this is a substack-hosted source."""
    if source.sender_domain != "substack.com":
        return None
    local = source.sender_email.split("@")[0]
    # Common patterns: urbankaoboy@substack.com → urbankaoboy
    # Some pubs use their own username (e.g. thebitcoinlayer, quoththeraven)
    return local


def fetch_substack_rss(
    slug: str,
    source_id: str,
    max_items: int = 20,
    tags: list[str] | None = None,
) -> list[RawDocument]:
    """Fetch one Substack publication's feed as RawDocuments."""
    url = f"https://{slug}.substack.com/feed"
    try:
        xml = fetch_feed(url, timeout=15.0)
    except Exception as e:
        logger.warning("Failed to fetch substack feed %s: %s", url, e)
        return []

    docs = parse_feed(xml, source_id=source_id, max_items=max_items)
    if tags:
        for d in docs:
            d.tags = list(tags)
    logger.info("Substack RSS %s -> %d posts", slug, len(docs))
    return docs


def fetch_all_configured_substacks(max_items_per_source: int = 10) -> list[RawDocument]:
    """Fetch RSS for every configured NEWSLETTER_SOURCES substack.

    Returns a combined list of RawDocuments across all substack-hosted
    sources. Safe to run alongside Gmail ingestion — dedup at DB layer.
    """
    out: list[RawDocument] = []
    for source in NEWSLETTER_SOURCES:
        slug = substack_slug(source)
        if not slug:
            continue
        try:
            out.extend(fetch_substack_rss(
                slug=slug,
                source_id=source.source_id,
                max_items=max_items_per_source,
                tags=["substack", "rss"] + list(source.tags),
            ))
        except Exception as e:
            logger.warning("Substack fetch failed for %s: %s", source.source_id, e)
    return out


def fetch_substack_by_url(post_url: str, source_id: str) -> RawDocument | None:
    """Fetch a specific Substack post by URL (HTML scrape, not RSS).

    Useful when you know a specific post URL and want to ingest it
    even if it's not in the recent RSS feed.

    TODO: implement HTML fetch + readability-style text extraction.
    For now, RSS feeds contain the full post content, so prefer those.
    """
    raise NotImplementedError(
        "One-off URL fetch: use RSS instead, or implement HTML scraping "
        "via httpx + BeautifulSoup."
    )

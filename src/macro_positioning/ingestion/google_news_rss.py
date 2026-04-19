"""Google News RSS connector — no API key, no rate limits (within reason).

URL patterns:
  Query:   https://news.google.com/rss/search?q={query}&hl=en-US
  Macro:   https://news.google.com/rss/search?q=macro+economics&hl=en-US

Use for broad macro headlines + specific asset class tracking.
Builds on the lightweight rss_connector stdlib parser.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

from macro_positioning.core.models import RawDocument
from macro_positioning.ingestion.rss_connector import fetch_feed, parse_feed

logger = logging.getLogger(__name__)

# Pre-built queries for our market buckets
MACRO_QUERIES: dict[str, str] = {
    "inflation": "inflation CPI PCE",
    "rates": "Federal Reserve interest rates Treasury yields",
    "equities": "stock market S&P 500 Nasdaq",
    "commodities": "gold oil commodity prices",
    "fx": "US dollar DXY currency markets",
    "crypto": "Bitcoin crypto",
    "geopolitics": "geopolitics tariffs trade war",
    "labor": "jobs unemployment payrolls labor market",
    "housing": "housing market mortgage",
}

SOURCE_ID = "google_news"


def build_rss_url(query: str, language: str = "en-US") -> str:
    return f"https://news.google.com/rss/search?q={quote(query)}&hl={language}"


def fetch_query(query: str, max_items: int = 20, tag_topic: str = "") -> list[RawDocument]:
    """Fetch Google News RSS results for an arbitrary query.

    Uses rss_connector's stdlib parser. Tags each document with
    ["google_news"] or ["google_news", tag_topic] when a topic label is set.
    """
    url = build_rss_url(query)
    xml = fetch_feed(url)
    docs = parse_feed(xml, source_id=SOURCE_ID, max_items=max_items)

    tags = ["google_news"]
    if tag_topic:
        tags.append(tag_topic)

    # rss_connector returns docs with empty tags; annotate them.
    for doc in docs:
        doc.tags = list(tags)

    logger.info(
        "Google News '%s' (topic=%s) -> %d items", query, tag_topic or "-", len(docs)
    )
    return docs


def fetch_topic(topic: str, max_items: int = 20) -> list[RawDocument]:
    """Fetch news for a macro topic (inflation, rates, commodities, etc.)."""
    query = MACRO_QUERIES.get(topic, topic)
    return fetch_query(query, max_items=max_items, tag_topic=topic)


def fetch_all_macro_topics(max_items_per_topic: int = 10) -> list[RawDocument]:
    """Pull all predefined macro topic feeds in one pass."""
    out: list[RawDocument] = []
    for topic in MACRO_QUERIES:
        try:
            out.extend(fetch_topic(topic, max_items=max_items_per_topic))
        except Exception as e:
            logger.warning("Failed to fetch topic %s: %s", topic, e)
    return out

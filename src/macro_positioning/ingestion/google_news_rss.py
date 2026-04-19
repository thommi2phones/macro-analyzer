"""Google News RSS connector — no API key, no rate limits (within reason).

URL patterns:
  Topic:   https://news.google.com/rss/headlines/section/topic/BUSINESS
  Query:   https://news.google.com/rss/search?q={query}&hl=en-US
  Macro:   https://news.google.com/rss/search?q=macro+economics&hl=en-US

Use for broad macro headlines + specific asset class tracking.

TODO(stream-a): fully implement using existing rss_connector.py as a base.
"""

from __future__ import annotations

import logging

from macro_positioning.core.models import RawDocument

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


def build_rss_url(query: str, language: str = "en-US") -> str:
    from urllib.parse import quote
    return f"https://news.google.com/rss/search?q={quote(query)}&hl={language}"


def fetch_topic(topic: str, max_items: int = 20) -> list[RawDocument]:
    """Fetch news for a macro topic (inflation, rates, commodities, etc.)."""
    query = MACRO_QUERIES.get(topic, topic)
    return fetch_query(query, max_items=max_items, tag_topic=topic)


def fetch_query(query: str, max_items: int = 20, tag_topic: str = "") -> list[RawDocument]:
    """Fetch Google News RSS results for an arbitrary query.

    TODO(stream-a): use existing rss_connector.parse_feed + httpx to fetch.
    Map each item to RawDocument with:
      source_id="google_news"
      tags=["google_news", tag_topic] if tag_topic else ["google_news"]
    """
    raise NotImplementedError("Stream A: implement using existing rss_connector")


def fetch_all_macro_topics(max_items_per_topic: int = 10) -> list[RawDocument]:
    """Pull all predefined macro topic feeds in one pass."""
    out: list[RawDocument] = []
    for topic in MACRO_QUERIES:
        try:
            out.extend(fetch_topic(topic, max_items=max_items_per_topic))
        except Exception as e:
            logger.warning("Failed to fetch topic %s: %s", topic, e)
    return out

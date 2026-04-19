"""Finnhub per-ticker news + sentiment connector.

Free tier: 60 calls/min.
API docs: https://finnhub.io/docs/api

Endpoints used:
  GET /company-news?symbol={ticker}&from={date}&to={date}
  GET /news?category=general (broad macro news)
  GET /news-sentiment?symbol={ticker} (aggregated sentiment)

TODO(stream-a): fully implement — this is a stub.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from macro_positioning.core.models import RawDocument
from macro_positioning.core.settings import settings

logger = logging.getLogger(__name__)

FINNHUB_BASE = "https://finnhub.io/api/v1"


def fetch_company_news(
    symbol: str,
    days: int = 7,
    api_key: str | None = None,
) -> list[RawDocument]:
    """Fetch recent news for a specific ticker.

    TODO(stream-a):
      - GET {FINNHUB_BASE}/company-news?symbol={symbol}&from=...&to=...
      - Map each item to RawDocument:
          source_id=f"finnhub_{symbol}",
          title=item["headline"],
          url=item["url"],
          raw_text=item["summary"],
          published_at=datetime.fromtimestamp(item["datetime"]),
          tags=["finnhub", symbol.lower()]
    """
    raise NotImplementedError("Stream A: implement Finnhub company news")


def fetch_general_news(
    category: str = "general",
    api_key: str | None = None,
) -> list[RawDocument]:
    """Fetch broad market news.

    Categories: general, forex, crypto, merger
    """
    raise NotImplementedError("Stream A: implement Finnhub general news")


def fetch_news_sentiment(symbol: str, api_key: str | None = None) -> dict:
    """Get aggregated news sentiment for a ticker.

    Returns a dict with buzz, sentiment score, etc. This is NOT a RawDocument;
    it feeds into the brain as a market observation instead.
    """
    raise NotImplementedError("Stream A: implement Finnhub sentiment")

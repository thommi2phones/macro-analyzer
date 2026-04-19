"""Finnhub per-ticker news + sentiment connector.

Free tier: 60 calls/min.
API docs: https://finnhub.io/docs/api

Endpoints used:
  GET /company-news?symbol={ticker}&from={date}&to={date}
  GET /news?category=general (broad macro news)
  GET /news-sentiment?symbol={ticker} (aggregated sentiment)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

from macro_positioning.core.models import RawDocument
from macro_positioning.core.settings import settings

logger = logging.getLogger(__name__)

FINNHUB_BASE = "https://finnhub.io/api/v1"
DEFAULT_TIMEOUT = 20.0


def _resolve_key(api_key: str | None) -> str:
    key = api_key or settings.finnhub_api_key
    if not key:
        raise RuntimeError(
            "Finnhub API key not configured. Set MPA_FINNHUB_API_KEY or pass api_key."
        )
    return key


def _get(path: str, params: dict, api_key: str | None, timeout: float = DEFAULT_TIMEOUT):
    key = _resolve_key(api_key)
    merged = {**params, "token": key}
    with httpx.Client(timeout=timeout) as client:
        resp = client.get(f"{FINNHUB_BASE}{path}", params=merged)
        resp.raise_for_status()
        return resp.json()


def _item_to_document(item: dict, source_id: str, extra_tags: list[str]) -> RawDocument | None:
    title = (item.get("headline") or "").strip()
    if not title:
        return None
    summary = (item.get("summary") or "").strip()
    url = item.get("url") or None
    ts = item.get("datetime")
    try:
        published = datetime.fromtimestamp(int(ts), tz=timezone.utc) if ts else datetime.now(timezone.utc)
    except (TypeError, ValueError, OSError):
        published = datetime.now(timezone.utc)
    raw_text = summary or title
    return RawDocument(
        source_id=source_id,
        title=title,
        url=url,
        published_at=published,
        author=item.get("source") or None,
        content_type="article",
        raw_text=raw_text,
        tags=extra_tags,
    )


def fetch_company_news(
    symbol: str,
    days: int = 7,
    api_key: str | None = None,
) -> list[RawDocument]:
    """Fetch recent news for a specific ticker via /company-news."""
    symbol = symbol.upper().strip()
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=max(days, 1))
    params = {
        "symbol": symbol,
        "from": start.isoformat(),
        "to": today.isoformat(),
    }
    try:
        payload = _get("/company-news", params, api_key)
    except Exception as e:
        logger.warning("Finnhub company-news fetch failed for %s: %s", symbol, e)
        return []

    if not isinstance(payload, list):
        logger.warning("Finnhub company-news unexpected shape for %s: %r", symbol, type(payload))
        return []

    docs: list[RawDocument] = []
    source_id = f"finnhub_{symbol.lower()}"
    for item in payload:
        doc = _item_to_document(
            item,
            source_id=source_id,
            extra_tags=["finnhub", symbol.lower()],
        )
        if doc is not None:
            docs.append(doc)
    logger.info("Finnhub company-news %s -> %d items", symbol, len(docs))
    return docs


def fetch_general_news(
    category: str = "general",
    api_key: str | None = None,
) -> list[RawDocument]:
    """Fetch broad market news via /news?category=.

    Categories: general, forex, crypto, merger
    """
    try:
        payload = _get("/news", {"category": category}, api_key)
    except Exception as e:
        logger.warning("Finnhub general-news fetch failed (%s): %s", category, e)
        return []

    if not isinstance(payload, list):
        return []

    docs: list[RawDocument] = []
    source_id = f"finnhub_{category}"
    for item in payload:
        doc = _item_to_document(
            item,
            source_id=source_id,
            extra_tags=["finnhub", category],
        )
        if doc is not None:
            docs.append(doc)
    logger.info("Finnhub general-news %s -> %d items", category, len(docs))
    return docs


def fetch_news_sentiment(symbol: str, api_key: str | None = None) -> dict:
    """Get aggregated news sentiment for a ticker via /news-sentiment.

    Returns a dict with buzz, sentiment score, etc. Not a RawDocument.
    """
    symbol = symbol.upper().strip()
    try:
        payload = _get("/news-sentiment", {"symbol": symbol}, api_key)
    except Exception as e:
        logger.warning("Finnhub sentiment fetch failed for %s: %s", symbol, e)
        return {"symbol": symbol, "error": str(e)}

    if not isinstance(payload, dict):
        return {"symbol": symbol, "error": "unexpected response"}

    buzz = payload.get("buzz") or {}
    sentiment = payload.get("sentiment") or {}
    return {
        "symbol": payload.get("symbol", symbol),
        "buzz": {
            "articles_in_last_week": buzz.get("articlesInLastWeek"),
            "buzz": buzz.get("buzz"),
            "weekly_average": buzz.get("weeklyAverage"),
        },
        "sentiment": {
            "bearish_percent": sentiment.get("bearishPercent"),
            "bullish_percent": sentiment.get("bullishPercent"),
        },
        "company_news_score": payload.get("companyNewsScore"),
        "sector_average_bullish_percent": payload.get("sectorAverageBullishPercent"),
        "sector_average_news_score": payload.get("sectorAverageNewsScore"),
    }

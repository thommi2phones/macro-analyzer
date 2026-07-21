"""Unusual Whales free-Twitter feed scraper, via RSS bridge.

UW's actual flow product is paid. Their public Twitter is the only free
surface, and X retired its public API in 2023. We capture it via
`rsshub.app` which proxies Twitter into RSS at no cost — when it works.

This source is best-effort by design: bridge instances rotate, get rate-
limited, or vanish. We try a primary, fall back to a secondary, then
silently return zero events. The funnel records a partial-success
cursor so the next morning_run just tries again.

If the user wants to swap in their own bridge (e.g. self-hosted rsshub),
override `BRIDGE_URLS` via env var `UW_RSS_BRIDGE_URLS` (comma-sep).
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Iterable, Optional
from xml.etree import ElementTree as ET

from macro_positioning.insiders.base import ScrapedEvent


log = logging.getLogger(__name__)


SOURCE_SLUG = "uw_twitter"
CHANNEL = "social"

# Try in order; first one that returns 200 wins.
_DEFAULT_BRIDGES = [
    "https://rsshub.app/twitter/user/unusual_whales",
    "https://rss.app/feeds/_PLACEHOLDER_unusual_whales.xml",
]


def _bridge_urls() -> list[str]:
    raw = os.environ.get("UW_RSS_BRIDGE_URLS", "")
    if raw:
        return [u.strip() for u in raw.split(",") if u.strip()]
    return _DEFAULT_BRIDGES


_UA = "macro-analyzer/0.1 (personal research)"

_TICKER_IN_TWEET = re.compile(r"\$([A-Z][A-Z0-9.\-]{0,5})\b")


def _fetch_first_working_bridge() -> Optional[bytes]:
    import httpx  # type: ignore

    for url in _bridge_urls():
        try:
            with httpx.Client(timeout=20.0, headers={"User-Agent": _UA},
                              follow_redirects=True) as client:
                resp = client.get(url)
                if resp.status_code == 200 and resp.content:
                    return resp.content
                log.debug("UW bridge %s returned %s", url, resp.status_code)
        except Exception as exc:  # noqa: BLE001
            log.debug("UW bridge %s failed: %s", url, exc)
            continue
    return None


def _iso_from_pubdate(pub: str) -> str:
    try:
        return parsedate_to_datetime(pub).date().isoformat()
    except Exception:  # noqa: BLE001
        return datetime.utcnow().date().isoformat()


def fetch_since(
    cursor: Optional[str],
    *,
    since: Optional[str] = None,
    **_kwargs,
) -> Iterable[ScrapedEvent]:
    body = _fetch_first_working_bridge()
    if body is None:
        log.info("UW Twitter bridge: no working source; skipping (expected)")
        return

    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        log.warning("UW bridge XML parse failed: %s", exc)
        return

    # RSS 2.0 standard fields.
    cursor_id = cursor or ""
    for item in root.findall(".//item"):
        guid = (item.findtext("guid") or item.findtext("link") or "").strip()
        if not guid:
            continue
        if guid == cursor_id:
            break
        title = (item.findtext("title") or "").strip()
        desc = (item.findtext("description") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        iso = _iso_from_pubdate(pub)
        if since and iso < since:
            continue

        # Strip HTML tags out of description quickly.
        text = re.sub(r"<[^>]+>", " ", desc)
        text = re.sub(r"\s+", " ", text).strip()
        combined = (title + " " + text).strip()

        tickers = sorted({m.group(1) for m in _TICKER_IN_TWEET.finditer(combined)})

        yield ScrapedEvent(
            source_slug=SOURCE_SLUG,
            channel=CHANNEL,
            external_id=guid,
            filed_at=iso,
            actor_name="Unusual Whales",
            principal_name="Unusual Whales",
            actor_relationship="self",
            tickers=tickers,
            amount_range=None,
            transaction_type="tweet",
            raw_text=combined,
            source_url=item.findtext("link") or "",
        )

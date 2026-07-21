"""StockTwits trending-symbols scraper.

Free first-party endpoint, no key. We pull the trending list once per
day and emit one ScrapedEvent per symbol.

Treated as a low-conviction watchlist nudge; the conviction default for
the `(social, other)` bucket in ingest.py is 1.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Iterable, Optional

from macro_positioning.insiders.base import ScrapedEvent


log = logging.getLogger(__name__)


SOURCE_SLUG = "stocktwits"
CHANNEL = "social"

_URL = "https://api.stocktwits.com/api/2/trending/symbols.json"
_UA = "macro-analyzer/0.1 (personal research)"

_DISPLAY = "StockTwits trending"


def _fetch_trending() -> dict:
    import httpx  # type: ignore

    with httpx.Client(timeout=30.0, headers={"User-Agent": _UA}) as client:
        resp = client.get(_URL)
        resp.raise_for_status()
        return resp.json()


def fetch_since(
    cursor: Optional[str],
    *,
    since: Optional[str] = None,
    **_kwargs,
) -> Iterable[ScrapedEvent]:
    today_iso = datetime.now(UTC).date().isoformat()
    cursor_day = (cursor or "").split("#", 1)[0] if cursor else None
    if cursor_day == today_iso:
        return

    try:
        payload = _fetch_trending()
    except Exception as exc:  # noqa: BLE001
        log.warning("StockTwits trending fetch failed: %s", exc)
        return

    for entry in payload.get("symbols", [])[:25]:
        ticker = (entry.get("symbol") or "").strip().upper()
        if not ticker:
            continue
        name = entry.get("title") or entry.get("name") or ""
        external_id = f"{today_iso}#stocktwits#{ticker}"
        yield ScrapedEvent(
            source_slug=SOURCE_SLUG,
            channel=CHANNEL,
            external_id=external_id,
            filed_at=today_iso,
            actor_name=_DISPLAY,
            principal_name=_DISPLAY,
            actor_relationship="self",
            tickers=[ticker],
            amount_range=None,
            transaction_type="trending",
            raw_text=f"StockTwits trending: {ticker} ({name})",
            source_url=f"https://stocktwits.com/symbol/{ticker}",
        )

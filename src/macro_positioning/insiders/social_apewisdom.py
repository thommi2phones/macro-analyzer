"""ApeWisdom Reddit/Discord mention-count scraper.

ApeWisdom aggregates ticker mentions across WSB and related communities.
Free JSON endpoint, no key. We pull a daily snapshot of the top ~50 by
mention count and emit one ScrapedEvent per ticker whose rank jumped
into the top N or whose 24h mention count more than tripled — that's
the "rank spike" signal.

`actor_name` is "WallStreetBets" (or whichever filter slug), so each
filter becomes its own author row and the per-author leaderboard
naturally compares Reddit-trend signal quality against Form 4, PTRs, etc.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Iterable, Optional

from macro_positioning.insiders.base import ScrapedEvent


log = logging.getLogger(__name__)


SOURCE_SLUG = "apewisdom"
CHANNEL = "social"

_URL_TMPL = "https://apewisdom.io/api/v1.0/filter/{filter_slug}"
_UA = "macro-analyzer/0.1 (personal research)"

# Filters to pull. Each becomes its own author.
_FILTERS = [
    ("wallstreetbets", "WallStreetBets"),
    ("stocks", "r/stocks"),
    ("options", "r/options"),
]

_TOP_N = 25
_SPIKE_MULT = 3.0  # mentions_24h_ago × 3 = spike threshold


def _fetch_filter(slug: str) -> dict:
    import httpx  # type: ignore

    with httpx.Client(timeout=30.0, headers={"User-Agent": _UA}) as client:
        resp = client.get(_URL_TMPL.format(filter_slug=slug))
        resp.raise_for_status()
        return resp.json()


def _events_from_response(payload: dict, *, filter_slug: str, display: str,
                          today_iso: str) -> Iterable[ScrapedEvent]:
    results = payload.get("results") or []
    for row in results[:_TOP_N]:
        ticker = (row.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        mentions = int(row.get("mentions") or 0)
        prior = int(row.get("mentions_24h_ago") or 0)
        rank = int(row.get("rank") or 0)
        prior_rank = int(row.get("rank_24h_ago") or 9999)

        is_spike = prior > 0 and mentions > prior * _SPIKE_MULT
        is_new_to_top = prior_rank > _TOP_N and rank <= _TOP_N
        if not (is_spike or is_new_to_top):
            continue

        bits = [
            f"{display} {ticker} #{rank}",
            f"mentions={mentions}",
            f"prior24h={prior}",
        ]
        if is_spike:
            bits.append(f"spike ×{mentions / max(prior, 1):.1f}")
        if is_new_to_top:
            bits.append(f"new-to-top (was #{prior_rank})")
        raw = " ".join(bits)

        # external_id is per-day-per-filter-per-ticker so the cursor
        # advances daily without dropping repeat-trending names.
        external_id = f"{today_iso}#{filter_slug}#{ticker}"

        yield ScrapedEvent(
            source_slug=SOURCE_SLUG,
            channel=CHANNEL,
            external_id=external_id,
            filed_at=today_iso,
            actor_name=display,
            principal_name=display,
            actor_relationship="self",
            tickers=[ticker],
            amount_range=None,
            transaction_type="rank_spike" if is_spike else "trending",
            raw_text=raw,
            source_url=f"https://apewisdom.io/{filter_slug}/",
        )


def fetch_since(
    cursor: Optional[str],
    *,
    since: Optional[str] = None,
    **_kwargs,
) -> Iterable[ScrapedEvent]:
    today_iso = datetime.now(UTC).date().isoformat()
    cursor_day = (cursor or "").split("#", 1)[0] if cursor else None
    if cursor_day == today_iso:
        # Already pulled today's snapshot.
        return

    for slug, display in _FILTERS:
        try:
            payload = _fetch_filter(slug)
        except Exception as exc:  # noqa: BLE001
            log.warning("ApeWisdom fetch failed for %s: %s", slug, exc)
            continue
        yield from _events_from_response(
            payload, filter_slug=slug, display=display, today_iso=today_iso,
        )

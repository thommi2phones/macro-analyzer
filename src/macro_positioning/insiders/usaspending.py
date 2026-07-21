"""USAspending.gov v2 spending_by_award scraper.

We pull new contract awards above a $10M floor in a rolling daily window
and emit one ScrapedEvent per award. The recipient is the actor; the
awarding agency is captured in the body text.

No ticker resolution v1 (most contractors are private or hard to map);
the watchlist scorer just sees this as macro/sector tilt context.

Public API, no key. Reference contract:
https://github.com/fedspendingtransparency/usaspending-api/blob/master/usaspending_api/api_contracts/contracts/v2/search/spending_by_award.md
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Iterable, Optional

from macro_positioning.insiders.base import ScrapedEvent


log = logging.getLogger(__name__)


SOURCE_SLUG = "usaspending"
CHANNEL = "fed_spend"

_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
_UA = "macro-analyzer/0.1 (personal research)"

# Default daily floor — bigger than the $1M default to keep noise down.
_DEFAULT_FLOOR = 10_000_000

# Contract award type codes (A=BPA Call, B=Purchase Order, C=Delivery Order,
# D=Definitive Contract). Pure-contract; excludes grants/loans to keep this
# tight.
_CONTRACT_CODES = ["A", "B", "C", "D"]


def _post_query(body: dict) -> dict:
    import httpx  # type: ignore

    with httpx.Client(timeout=60.0, headers={"User-Agent": _UA}) as client:
        resp = client.post(_URL, json=body)
        resp.raise_for_status()
        return resp.json()


def _window(since: Optional[str]) -> tuple[str, str]:
    end = datetime.now(UTC).date()
    if since:
        try:
            start = datetime.strptime(since, "%Y-%m-%d").date()
        except ValueError:
            start = end - timedelta(days=7)
    else:
        start = end - timedelta(days=7)
    return start.isoformat(), end.isoformat()


def fetch_since(
    cursor: Optional[str],
    *,
    since: Optional[str] = None,
    floor_usd: int = _DEFAULT_FLOOR,
    limit: int = 50,
    **_kwargs,
) -> Iterable[ScrapedEvent]:
    start, end = _window(since)
    body = {
        "subawards": False,
        "limit": limit,
        "page": 1,
        "filters": {
            "award_type_codes": _CONTRACT_CODES,
            "time_period": [{"start_date": start, "end_date": end}],
            "award_amounts": [{"lower_bound": floor_usd}],
        },
        "fields": [
            "Award ID",
            "Recipient Name",
            "Start Date",
            "End Date",
            "Award Amount",
            "Awarding Agency",
            "Awarding Sub Agency",
            "generated_internal_id",
        ],
        "sort": "Award Amount",
        "order": "desc",
    }

    try:
        payload = _post_query(body)
    except Exception as exc:  # noqa: BLE001
        log.warning("USAspending query failed: %s", exc)
        return

    cursor_id = cursor or ""
    for row in payload.get("results", []):
        award_id = row.get("Award ID") or row.get("generated_internal_id") or ""
        if not award_id:
            continue
        if award_id == cursor_id:
            break
        recipient = row.get("Recipient Name") or "Unknown recipient"
        amount = row.get("Award Amount") or 0
        agency = row.get("Awarding Agency") or ""
        sub_agency = row.get("Awarding Sub Agency") or ""
        start_date = row.get("Start Date") or end
        url_id = row.get("generated_internal_id") or award_id

        raw = (
            f"{recipient} — ${amount:,.0f} — {agency}"
            + (f" / {sub_agency}" if sub_agency else "")
            + f" — start {start_date}"
        )

        yield ScrapedEvent(
            source_slug=SOURCE_SLUG,
            channel=CHANNEL,
            external_id=award_id,
            filed_at=start_date,
            actor_name=recipient,
            principal_name=recipient,
            actor_relationship="registrant",
            tickers=[],
            amount_range=f"${amount:,.0f}",
            transaction_type="award",
            raw_text=raw,
            source_url=f"https://www.usaspending.gov/award/{url_id}",
        )

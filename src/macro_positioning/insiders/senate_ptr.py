"""Senate Periodic Transaction Report (PTR) scraper.

Source: the timothycarambat/senate-stock-watcher-data GitHub mirror. The
official Senate eFD site requires captcha and has no bulk export; the
mirror is updated daily from eFD and exposes one flat JSON of all
transactions, which is exactly what we want.

JSON record shape (verified):
  {
    "transaction_date": "11/10/2020",   # MM/DD/YYYY
    "owner": "Spouse" | "Self" | "Joint" | "Dependent" | "DC" | ...
    "ticker": "BYND",                    # may be "--" for non-equities
    "asset_description": "Beyond Meat, Inc.",
    "asset_type": "Stock",
    "type": "Sale (Full)" | "Purchase" | "Exchange" | ...
    "amount": "$50,001 - $100,000",
    "comment": "--",
    "senator": "Ron L Wyden",
    "ptr_link": "https://efdsearch.senate.gov/search/view/ptr/<uuid>/"
  }

`external_id` = the PTR UUID parsed out of `ptr_link`, suffixed with a
row index inside that filing so multiple lines from the same PTR each
get a unique cursor key.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from macro_positioning.core.settings import settings

from macro_positioning.insiders.base import ScrapedEvent


log = logging.getLogger(__name__)


SOURCE_SLUG = "senate"
CHANNEL = "gov_insider"

_MIRROR_URL = (
    "https://raw.githubusercontent.com/timothycarambat/"
    "senate-stock-watcher-data/master/aggregate/all_transactions.json"
)
_UA = "macro-analyzer/0.1 (personal research)"

_PTR_UUID = re.compile(r"/ptr/([0-9a-f-]{36})/?", re.IGNORECASE)

_OWNER_MAP = {
    "self": "self",
    "joint": "self",
    "spouse": "spouse",
    "dependent": "dependent",
    "dc": "dependent",
    "sp": "spouse",
}


def _cache_path() -> Path:
    d = settings.base_dir / "cache" / "insiders" / "senate"
    d.mkdir(parents=True, exist_ok=True)
    return d / "all_transactions.json"


def _fetch_mirror_json() -> list[dict]:
    import httpx  # type: ignore

    cache = _cache_path()
    # Re-download on every run (the mirror is small relative to the cost
    # of stale data). Persist for offline test fall-back only.
    log.info("Downloading Senate stock watcher mirror JSON")
    with httpx.Client(timeout=60.0, headers={"User-Agent": _UA}, follow_redirects=True) as client:
        resp = client.get(_MIRROR_URL)
        resp.raise_for_status()
        cache.write_bytes(resp.content)
        return resp.json()


def _to_iso(date_str: str) -> str:
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt).date().isoformat()
        except ValueError:
            continue
    return date_str  # leave verbatim if we can't parse — sorts lexicographically later


def _extract_ptr_uuid(ptr_link: str) -> Optional[str]:
    if not ptr_link:
        return None
    m = _PTR_UUID.search(ptr_link)
    return m.group(1) if m else None


def record_to_event(record: dict, *, row_index: int) -> Optional[ScrapedEvent]:
    ticker = (record.get("ticker") or "").strip().upper()
    if not ticker or ticker == "--":
        return None  # non-equity rows have no actionable ticker for us

    senator = (record.get("senator") or "").strip()
    if not senator:
        return None

    ptr_uuid = _extract_ptr_uuid(record.get("ptr_link", "")) or f"NO-PTR-{row_index}"
    external_id = f"{ptr_uuid}#{row_index}"

    owner_raw = (record.get("owner") or "").strip().lower()
    relationship = _OWNER_MAP.get(owner_raw, "self")

    txn_type_raw = (record.get("type") or "").strip().lower()
    if "purchase" in txn_type_raw or "buy" in txn_type_raw:
        transaction_type = "purchase"
    elif "sale" in txn_type_raw or "sell" in txn_type_raw:
        transaction_type = "sale"
    elif "exchange" in txn_type_raw:
        transaction_type = "exchange"
    else:
        transaction_type = "disclosure"

    actor_name = senator if relationship == "self" else f"{senator} ({owner_raw})"

    raw_text = (
        f"{senator} | {owner_raw or 'self'} | {ticker} "
        f"{record.get('asset_description', '')} | "
        f"{record.get('type', '')} | {record.get('amount', '')} | "
        f"filed {record.get('transaction_date', '')}"
    )

    return ScrapedEvent(
        source_slug=SOURCE_SLUG,
        channel=CHANNEL,
        external_id=external_id,
        filed_at=_to_iso(record.get("transaction_date") or ""),
        actor_name=actor_name,
        principal_name=senator,
        actor_relationship=relationship,
        tickers=[ticker],
        amount_range=record.get("amount"),
        transaction_type=transaction_type,
        raw_text=raw_text,
        source_url=record.get("ptr_link"),
    )


def iter_events_from_json(
    records: list[dict],
    *,
    since: Optional[str] = None,
    cursor: Optional[str] = None,
    max_records: Optional[int] = None,
) -> Iterable[ScrapedEvent]:
    # The mirror is published newest-last in practice; sort by transaction_date
    # so since-filtering and cursor logic are deterministic regardless.
    enriched = []
    for idx, rec in enumerate(records):
        iso = _to_iso(rec.get("transaction_date") or "")
        enriched.append((iso, idx, rec))
    enriched.sort(key=lambda t: (t[0], t[1]))

    # Pull cursor's filing UUID out so we can resume after it (the trailing
    # row-index doesn't matter here — we always reprocess a whole PTR).
    cursor_uuid = (cursor or "").split("#", 1)[0] if cursor else None
    passed_cursor = cursor_uuid is None

    emitted = 0
    for iso, idx, rec in enriched:
        if since and iso < since:
            continue
        ptr_uuid = _extract_ptr_uuid(rec.get("ptr_link", ""))
        if not passed_cursor:
            if ptr_uuid and ptr_uuid == cursor_uuid:
                passed_cursor = True
            continue
        event = record_to_event(rec, row_index=idx)
        if event is None:
            continue
        yield event
        emitted += 1
        if max_records is not None and emitted >= max_records:
            break


def fetch_since(
    cursor: Optional[str],
    *,
    since: Optional[str] = None,
    max_records: Optional[int] = None,
    **_kwargs,
) -> Iterable[ScrapedEvent]:
    """Default scraper entry. Downloads the mirror JSON and walks new rows."""
    records = _fetch_mirror_json()
    yield from iter_events_from_json(
        records, since=since, cursor=cursor, max_records=max_records,
    )


# Test-only helper: parse a local JSON file (used in fixtures).
def iter_events_from_path(
    path: Path,
    *,
    since: Optional[str] = None,
    cursor: Optional[str] = None,
) -> Iterable[ScrapedEvent]:
    records = json.loads(Path(path).read_text())
    yield from iter_events_from_json(records, since=since, cursor=cursor)

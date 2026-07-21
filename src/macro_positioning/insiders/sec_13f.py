"""SEC Form 13F-HR scraper for a curated list of large institutional managers.

13F-HR quarterly filings list every position held >$200k by institutional
managers >$100M AUM. We diff the latest filing against the prior one for
each watched CIK and emit one ScrapedEvent per change:

  - new position    -> transaction_type="new"
  - increased       -> transaction_type="grown"
  - decreased       -> transaction_type="trimmed"
  - exited          -> transaction_type="exited"

CUSIP → ticker resolution is best-effort via OpenFIGI's free /v3/mapping
endpoint (no key, 25 req/min unauthed). When that fails we leave tickers
empty; the documents row still ingests, just won't move the watchlist.

Managers are curated in `config/13f_watch_ciks.json`.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Iterable, Optional
from xml.etree import ElementTree as ET

from macro_positioning.core.settings import settings
from macro_positioning.insiders import edgar_client
from macro_positioning.insiders.base import ScrapedEvent


log = logging.getLogger(__name__)


SOURCE_SLUG = "form13f"
CHANNEL = "large_holder"

# EDGAR submissions API gives us recent filings for a single CIK.
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

_INFO_TABLE_HREF = re.compile(
    r'href="(/Archives/edgar/data/\d+/\d+/[^"]*?(?:infotable|form13fInfoTable)[^"]*?\.xml)"',
    re.IGNORECASE,
)

# OpenFIGI CUSIP -> ticker resolver (free, no key).
_FIGI_URL = "https://api.openfigi.com/v3/mapping"


def _watched_managers() -> list[dict]:
    path = settings.base_dir / "config" / "13f_watch_ciks.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    # Dedupe by CIK while keeping the first name seen.
    seen: dict[str, dict] = {}
    for m in data.get("managers", []):
        cik = m.get("cik", "").lstrip("0") or m.get("cik", "")
        if cik and cik not in seen:
            seen[cik] = {"cik": cik, "name": m.get("name", cik)}
    return list(seen.values())


def _recent_13f_filings(cik: str) -> list[dict]:
    """Return list of {accession, filing_date, primary_doc} sorted newest-first."""
    body = edgar_client.get(_SUBMISSIONS_URL.format(cik=cik.zfill(10)))
    payload = json.loads(body)
    recent = payload.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accs = recent.get("accessionNumber", [])
    dates = recent.get("filingDate", [])
    primary = recent.get("primaryDocument", [])
    out: list[dict] = []
    for i, form in enumerate(forms):
        if form == "13F-HR":
            out.append({
                "accession": accs[i],
                "filing_date": dates[i],
                "primary_doc": primary[i],
            })
    return out


def _info_table_for(cik: str, accession: str) -> Optional[bytes]:
    """Fetch the info-table XML inside a 13F-HR accession."""
    acc_dir = accession.replace("-", "")
    index_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_dir}/"
    body = edgar_client.get_text(index_url)
    m = _INFO_TABLE_HREF.search(body)
    if not m:
        return None
    return edgar_client.get("https://www.sec.gov" + m.group(1))


def _parse_info_table(xml_bytes: bytes) -> dict[str, dict]:
    """Return {cusip: {nameOfIssuer, value, sshPrnamt}}."""
    # 13F info tables use a namespace.
    text = xml_bytes.decode("utf-8", errors="replace")
    # Strip namespaces — easier than juggling them across XSD versions.
    text = re.sub(r"\sxmlns(:\w+)?=\"[^\"]+\"", "", text)
    root = ET.fromstring(text)
    out: dict[str, dict] = {}
    for entry in root.findall(".//infoTable"):
        cusip = (entry.findtext("cusip") or "").strip()
        if not cusip:
            continue
        value = entry.findtext("value") or "0"
        shares_el = entry.find("shrsOrPrnAmt")
        shares = shares_el.findtext("sshPrnamt") if shares_el is not None else "0"
        # Aggregate within a filing (same CUSIP can appear multiple times).
        prev = out.get(cusip)
        if prev:
            prev["value"] = str(int(prev["value"]) + int(value or 0))
            prev["shares"] = str(int(prev["shares"]) + int(shares or 0))
        else:
            out[cusip] = {
                "name": entry.findtext("nameOfIssuer") or "",
                "value": value or "0",
                "shares": shares or "0",
            }
    return out


# CUSIP -> ticker cache.
def _ticker_cache_path() -> Path:
    p = settings.base_dir / "cache" / "insiders" / "cusip_tickers.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_ticker_cache() -> dict[str, str]:
    p = _ticker_cache_path()
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def _save_ticker_cache(cache: dict[str, str]) -> None:
    _ticker_cache_path().write_text(json.dumps(cache))


def _resolve_cusips(cusips: list[str]) -> dict[str, str]:
    cache = _load_ticker_cache()
    todo = [c for c in cusips if c not in cache]
    if not todo:
        return {c: cache.get(c, "") for c in cusips}

    import httpx  # type: ignore

    # Batch 100 at a time, polite spacing.
    for i in range(0, len(todo), 100):
        chunk = todo[i:i + 100]
        payload = [{"idType": "ID_CUSIP", "idValue": c} for c in chunk]
        try:
            with httpx.Client(timeout=20.0, headers={"User-Agent": "macro-analyzer/0.1"}) as client:
                resp = client.post(_FIGI_URL, json=payload)
                if resp.status_code == 429:
                    time.sleep(6)
                    resp = client.post(_FIGI_URL, json=payload)
                resp.raise_for_status()
                results = resp.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("OpenFIGI lookup failed: %s", exc)
            break
        for cusip, result in zip(chunk, results):
            ticker = ""
            data = (result or {}).get("data") or []
            for row in data:
                if row.get("ticker"):
                    ticker = row["ticker"]
                    break
            cache[cusip] = ticker
        time.sleep(2.5)  # well under 25rpm
    _save_ticker_cache(cache)
    return {c: cache.get(c, "") for c in cusips}


def fetch_since(
    cursor: Optional[str],
    *,
    since: Optional[str] = None,
    **_kwargs,
) -> Iterable[ScrapedEvent]:
    """Per-manager: pull the latest two 13F-HR filings and diff."""
    managers = _watched_managers()
    if not managers:
        log.warning("No managers configured in config/13f_watch_ciks.json")
        return

    cursor_acc = (cursor or "").split("#", 1)[0] if cursor else None
    last_acc = None

    for mgr in managers:
        try:
            filings = _recent_13f_filings(mgr["cik"])
        except Exception as exc:  # noqa: BLE001
            log.warning("13F submissions fetch failed for %s: %s", mgr["name"], exc)
            continue
        if len(filings) < 2:
            log.debug("13F: %s has <2 filings, skipping diff", mgr["name"])
            continue

        latest, prior = filings[0], filings[1]
        if since and latest["filing_date"] < since:
            continue
        if cursor_acc and latest["accession"] == cursor_acc:
            continue

        try:
            latest_xml = _info_table_for(mgr["cik"], latest["accession"])
            prior_xml = _info_table_for(mgr["cik"], prior["accession"])
            if not latest_xml or not prior_xml:
                continue
            latest_pos = _parse_info_table(latest_xml)
            prior_pos = _parse_info_table(prior_xml)
        except Exception as exc:  # noqa: BLE001
            log.warning("13F parse failed for %s: %s", mgr["name"], exc)
            continue

        cusips = sorted(set(latest_pos) | set(prior_pos))
        tickers_for = _resolve_cusips(cusips)

        period_url = (
            f"https://www.sec.gov/cgi-bin/browse-edgar?"
            f"action=getcompany&CIK={mgr['cik']}&type=13F-HR&dateb=&owner=include&count=10"
        )

        for cusip in cusips:
            new = latest_pos.get(cusip)
            old = prior_pos.get(cusip)
            if new and not old:
                txn = "new"
            elif old and not new:
                txn = "exited"
            elif new and old and int(new["shares"]) > int(old["shares"]) * 1.05:
                txn = "grown"
            elif new and old and int(new["shares"]) < int(old["shares"]) * 0.95:
                txn = "trimmed"
            else:
                continue  # ~flat, skip

            ticker = tickers_for.get(cusip, "")
            name = (new or old)["name"]
            raw = (
                f"{mgr['name']} 13F {latest['filing_date']}: {txn} {name} "
                f"({ticker or 'CUSIP ' + cusip})"
            )

            yield ScrapedEvent(
                source_slug=SOURCE_SLUG,
                channel=CHANNEL,
                external_id=f"{latest['accession']}#{cusip}",
                filed_at=latest["filing_date"],
                actor_name=mgr["name"],
                principal_name=mgr["name"],
                actor_relationship="registrant",
                tickers=[ticker] if ticker else [],
                amount_range=None,
                transaction_type=txn,
                raw_text=raw,
                source_url=period_url,
            )
            last_acc = latest["accession"]

    _ = last_acc  # cursor advancement happens via funnel.set_cursor on the last event

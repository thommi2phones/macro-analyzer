"""SEC Schedule 13D / 13G scraper.

13D = activist or otherwise-material >5% stake. 13G = passive >5%. Both
disclose CUSIP-level new positions in public companies. 13D is the
single highest-signal feed in this whole package — it surfaces, in
~10 days, who just took a board-shaking position in whom.

Approach:
  - Atom feeds for `type=SC 13D` and `type=SC 13G` (and amendments
    13D/A, 13G/A) via the same `getcurrent` endpoint Form 4 uses.
  - For each filing's index, dig out the primary `.htm` cover page and
    parse the issuer ticker + filer name + percent-owned out of it via
    a few resilient regexes — cover pages are free-form text.

Conviction defaults are set by ingest.py: 13D buy = conviction 5,
13G = conviction 2 (WATCH).
"""

from __future__ import annotations

import html
import logging
import re
from typing import Iterable, Optional
from xml.etree import ElementTree as ET

from macro_positioning.insiders import edgar_client
from macro_positioning.insiders.base import ScrapedEvent


log = logging.getLogger(__name__)


SOURCE_SLUG = "sc_13d_13g"
CHANNEL = "large_holder"

_ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}
_ATOM_URL_TMPL = (
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent"
    "&type={qtype}&output=atom&count={count}"
)


# Cover-page heuristics. 13D/G cover pages are typeset text, not data —
# these patterns hit common boilerplate phrasings.
_TICKER_PAREN = re.compile(r"\(\s*Symbol\s*:?\s*([A-Z][A-Z0-9.\-]{0,5})\s*\)|"
                           r"Trading Symbol[^A-Z]{0,5}([A-Z][A-Z0-9.\-]{0,5})",
                           re.IGNORECASE)
_PERCENT = re.compile(r"Percent\s+of\s+Class\s+Represented[^0-9]{0,40}([0-9]{1,3}(?:\.[0-9]+)?)\s*%",
                      re.IGNORECASE)


def _atom_entries(qtype: str, count: int) -> list[dict]:
    url = _ATOM_URL_TMPL.format(qtype=qtype.replace(" ", "+"), count=count)
    body = edgar_client.get(url, use_cache=False)
    root = ET.fromstring(body)
    out = []
    for e in root.findall("a:entry", _ATOM_NS):
        title = html.unescape(e.findtext("a:title", default="", namespaces=_ATOM_NS))
        link_el = e.find("a:link", _ATOM_NS)
        href = link_el.get("href") if link_el is not None else ""
        updated = e.findtext("a:updated", default="", namespaces=_ATOM_NS)
        accession_id = e.findtext("a:id", default="", namespaces=_ATOM_NS)
        m = re.search(r"accession-number=([\d-]+)", accession_id)
        accession = m.group(1) if m else ""
        out.append({
            "title": title,
            "href": href,
            "updated": updated,
            "accession": accession,
            "form_type": qtype,
        })
    return out


_PRIMARY_DOC_HREF = re.compile(
    r'href="(/Archives/edgar/data/\d+/\d+/[^"]*?\.htm)"',
    re.IGNORECASE,
)


def _cover_text_for(index_url: str) -> tuple[str, str]:
    """Return (primary_doc_url, cover_text) for an accession index page.

    Picks the first `.htm` in the listing that isn't the index itself —
    that's almost always the actual filing.
    """
    body = edgar_client.get_text(index_url)
    primary = None
    for m in _PRIMARY_DOC_HREF.finditer(body):
        href = m.group(1)
        if href.endswith("-index.htm"):
            continue
        primary = "https://www.sec.gov" + href
        break
    if primary is None:
        return "", ""
    return primary, edgar_client.get_text(primary)


def _parse_title(title: str) -> tuple[str, str, str]:
    """Extract (form_type, filer_or_issuer_name, role) from an atom title.

    EDGAR titles look like "SC 13D - Filer Name (CIK) (Filer)" or
    "SC 13D - Issuer Name (CIK) (Issuer)". We return whichever appears.
    """
    # title format: "<FORM> - <NAME> (<CIK>) (<role>)"
    m = re.match(r"^(SC\s+13[DG](?:/A)?)\s*-\s*(.+?)\s*\(\d+\)\s*\((Filer|Issuer|Reporting)\)\s*$",
                 title, re.IGNORECASE)
    if not m:
        return ("", title.strip(), "")
    return (m.group(1).strip(), m.group(2).strip(), m.group(3).strip())


def fetch_since(
    cursor: Optional[str],
    *,
    count: int = 60,
    since: Optional[str] = None,
    **_kwargs,
) -> Iterable[ScrapedEvent]:
    cursor_acc = (cursor or "").split("#", 1)[0] if cursor else None
    seen_accessions: set[str] = set()

    for qtype in ("SC 13D", "SC 13G", "SC 13D/A", "SC 13G/A"):
        try:
            entries = _atom_entries(qtype, count)
        except Exception as exc:  # noqa: BLE001
            log.warning("Atom feed failed for %s: %s", qtype, exc)
            continue
        for entry in entries:
            acc = entry["accession"]
            if not acc or acc in seen_accessions:
                continue
            if cursor_acc and acc == cursor_acc:
                break
            if since:
                try:
                    if entry["updated"][:10] < since:
                        break
                except Exception:  # noqa: BLE001
                    pass
            seen_accessions.add(acc)

            form_type, name, role = _parse_title(entry["title"])
            if role.lower() == "issuer":
                # Skip the issuer-side echo of the same filing; the filer
                # entry is the one carrying the activist signal.
                continue

            try:
                primary_url, cover = _cover_text_for(entry["href"])
            except Exception as exc:  # noqa: BLE001
                log.debug("13D/G cover fetch failed acc=%s: %s", acc, exc)
                continue

            # Best-effort ticker + percent extraction from the cover.
            ticker = ""
            mt = _TICKER_PAREN.search(cover or "")
            if mt:
                ticker = (mt.group(1) or mt.group(2) or "").upper()
            percent = ""
            mp = _PERCENT.search(cover or "")
            if mp:
                percent = mp.group(1) + "%"

            is_d = "13D" in (form_type or "").upper()
            transaction_type = "new_or_grown" if is_d else "passive_5pct"

            raw_text = (
                f"{name} filed {form_type or '13D/G'} on {ticker or '<no ticker>'} "
                f"{('owning ' + percent) if percent else ''}"
            ).strip()

            yield ScrapedEvent(
                source_slug=SOURCE_SLUG,
                channel=CHANNEL,
                external_id=f"{acc}#0",
                filed_at=entry["updated"][:10],
                actor_name=name,
                principal_name=name,
                actor_relationship="registrant",
                tickers=[ticker] if ticker else [],
                amount_range=percent or None,
                transaction_type=transaction_type,
                raw_text=raw_text,
                source_url=primary_url or entry["href"],
            )

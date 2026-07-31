"""SEC Form 4 (and 5) scraper.

Pipeline:
  1. Pull the EDGAR "latest filings" atom feed filtered to type=4 (and 5).
  2. For each entry: dig out the accession number, walk the accession
     directory to find the `*form4*.xml` (or `form5_*.xml`) ownership
     document, fetch and parse.
  3. Emit one ScrapedEvent per non-derivative transaction. Related-party
     positions (Table II `directOrIndirectOwnership=I` with
     `natureOfOwnership` like "By Spouse" / "By Trust") attribute to the
     reporting owner as principal, with `actor_relationship` reflecting
     the disclosed linkage.

Cursor: the most recent accession number ingested. Entries newer than
the cursor (i.e. before it in the feed) are processed; older entries
are skipped.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime
from typing import Iterable, Optional
from xml.etree import ElementTree as ET

from macro_positioning.insiders import edgar_client
from macro_positioning.insiders.base import ScrapedEvent


log = logging.getLogger(__name__)


SOURCE_SLUG = "form4"
CHANNEL = "corp_insider"

_ATOM_URL_TMPL = (
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent"
    "&type={type}&output=atom&count={count}"
)

# We always pull the same count; the cursor cuts off older filings.
_DEFAULT_COUNT = 100

_ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}

# Form 4 XML uses no namespace.
# We pull only the fields we need (issuer, owner, relationship, txns).

_ACCESSION_FROM_HREF = re.compile(r"/Archives/edgar/data/(\d+)/(\d+)/([\d-]+)-index\.htm")
_FORM_XML_HREF = re.compile(
    r'href="(/Archives/edgar/data/\d+/\d+/[^"]*?(?:form4|form5)[^"]*?\.xml)"',
    re.IGNORECASE,
)

_NATURE_TO_RELATIONSHIP = {
    "spouse": "spouse",
    "child": "dependent",
    "children": "dependent",
    "minor": "dependent",
    "trust": "trust",
    "family trust": "trust",
    "llc": "llc",
    "partnership": "llc",
}


def _classify_relationship(
    direct_or_indirect: str,
    nature: str,
    is_director: bool,
    is_officer: bool,
    is_ten_pct: bool,
) -> str:
    if direct_or_indirect.upper() == "I" and nature:
        n = nature.lower()
        for key, rel in _NATURE_TO_RELATIONSHIP.items():
            if key in n:
                return rel
        return "family_other"
    if is_ten_pct:
        return "10pct_owner"
    if is_officer:
        return "officer"
    if is_director:
        return "director"
    return "self"


def _xtext(parent: Optional[ET.Element], path: str) -> str:
    if parent is None:
        return ""
    el = parent.find(path)
    if el is None:
        return ""
    # Form 4 values are nested as <value>...</value> children commonly.
    val = el.find("value")
    if val is not None and val.text:
        return val.text.strip()
    return (el.text or "").strip()


def parse_form4_xml(xml_bytes: bytes, *, accession: str, source_url: str) -> list[ScrapedEvent]:
    root = ET.fromstring(xml_bytes)
    issuer = root.find("issuer")
    issuer_ticker = _xtext(issuer, "issuerTradingSymbol").upper() if issuer is not None else ""
    issuer_name = _xtext(issuer, "issuerName") if issuer is not None else ""
    period = _xtext(root, "periodOfReport")

    owner = root.find("reportingOwner")
    owner_name = ""
    is_director = is_officer = is_ten_pct = False
    if owner is not None:
        owner_name = _xtext(owner.find("reportingOwnerId"), "rptOwnerName") \
            if owner.find("reportingOwnerId") is not None else ""
        rel = owner.find("reportingOwnerRelationship")
        if rel is not None:
            is_director = _xtext(rel, "isDirector") == "1"
            is_officer = _xtext(rel, "isOfficer") == "1"
            is_ten_pct = _xtext(rel, "isTenPercentOwner") == "1"

    out: list[ScrapedEvent] = []
    table = root.find("nonDerivativeTable")
    if table is None:
        return out

    for idx, txn in enumerate(table.findall("nonDerivativeTransaction")):
        coding = txn.find("transactionCoding")
        code = _xtext(coding, "transactionCode") if coding is not None else ""
        amounts = txn.find("transactionAmounts")
        ad_code = ""
        shares = ""
        price = ""
        if amounts is not None:
            ad_code = _xtext(amounts.find("transactionAcquiredDisposedCode"), "value") \
                if amounts.find("transactionAcquiredDisposedCode") is not None else ""
            # value-of-value patterns
            shares = _xtext(amounts, "transactionShares")
            price = _xtext(amounts, "transactionPricePerShare")
        txn_date = _xtext(txn, "transactionDate") or period

        ownership = txn.find("ownershipNature")
        d_or_i = ""
        nature = ""
        if ownership is not None:
            d_or_i = _xtext(ownership, "directOrIndirectOwnership")
            nature = _xtext(ownership, "natureOfOwnership")

        relationship = _classify_relationship(
            d_or_i, nature, is_director, is_officer, is_ten_pct,
        )

        if code in ("P",) or ad_code == "A" and code in ("P", "M", "A"):
            transaction_type = "purchase"
        elif code in ("S", "D") or ad_code == "D":
            transaction_type = "sale"
        else:
            transaction_type = "disclosure"

        # Actor name surfaces the linkage; principal stays the reporting
        # owner so the leaderboard joins right.
        if relationship not in ("self", "director", "officer", "10pct_owner") and nature:
            actor_name = f"{owner_name} (held {nature})"
        else:
            actor_name = owner_name

        bits = [
            owner_name,
            issuer_name,
            f"({issuer_ticker})" if issuer_ticker else "",
            f"code={code}",
            f"shares={shares}" if shares else "",
            f"@${price}" if price else "",
            f"AD={ad_code}" if ad_code else "",
            f"nature={nature}" if nature else "",
        ]
        raw_text = " ".join(b for b in bits if b)

        out.append(ScrapedEvent(
            source_slug=SOURCE_SLUG,
            channel=CHANNEL,
            external_id=f"{accession}#{idx}",
            filed_at=txn_date,
            actor_name=actor_name or owner_name,
            principal_name=owner_name,
            actor_relationship=relationship,
            tickers=[issuer_ticker] if issuer_ticker else [],
            amount_range=f"{shares} sh @ ${price}" if shares and price else None,
            transaction_type=transaction_type,
            raw_text=raw_text,
            source_url=source_url,
        ))
    return out


def _atom_entries(form_type: str = "4", count: int = _DEFAULT_COUNT) -> list[dict]:
    url = _ATOM_URL_TMPL.format(type=form_type, count=count)
    body = edgar_client.get(url, use_cache=False)  # always fresh for feeds
    root = ET.fromstring(body)
    entries = []
    for e in root.findall("a:entry", _ATOM_NS):
        title = e.findtext("a:title", default="", namespaces=_ATOM_NS)
        link_el = e.find("a:link", _ATOM_NS)
        href = link_el.get("href") if link_el is not None else ""
        updated = e.findtext("a:updated", default="", namespaces=_ATOM_NS)
        accession_id_text = e.findtext("a:id", default="", namespaces=_ATOM_NS)
        m = re.search(r"accession-number=([\d-]+)", accession_id_text)
        accession = m.group(1) if m else ""
        entries.append({
            "title": html.unescape(title),
            "href": href,
            "updated": updated,
            "accession": accession,
        })
    return entries


def _form_xml_url_from_index(index_url: str) -> Optional[str]:
    """Pull the form4/form5 XML href out of an accession index page.

    EDGAR index pages link the XSLT-*rendered* HTML view of the ownership
    doc (path segment `/xslF345X0N/…`), which parses as HTML, not the raw
    `<ownershipDocument>` XML our parser expects. The machine-readable XML
    is the sibling URL with that segment removed, so strip any `/xsl…/`.
    """
    body = edgar_client.get_text(index_url)
    m = _FORM_XML_HREF.search(body)
    if not m:
        return None
    href = re.sub(r"/xsl[^/]+/", "/", m.group(1))
    return "https://www.sec.gov" + href


def fetch_since(
    cursor: Optional[str],
    *,
    since: Optional[str] = None,
    count: int = _DEFAULT_COUNT,
    form_type: str = "4",
    **_kwargs,
) -> Iterable[ScrapedEvent]:
    """Walk the EDGAR Form 4 atom feed.

    Cursor = the most recent accession we've ingested. Newer entries (which
    appear above it in the feed) are processed; once we hit the cursor we
    stop. On first run (cursor=None) we ingest the full `count` window.
    """
    entries = _atom_entries(form_type=form_type, count=count)
    # Newest-first as published; we drain until cursor.
    cursor_acc = (cursor or "").split("#", 1)[0] if cursor else None
    for entry in entries:
        if cursor_acc and entry["accession"] == cursor_acc:
            break
        if since:
            try:
                upd = entry["updated"][:10]
                if upd < since:
                    break
            except Exception:  # noqa: BLE001
                pass
        index_url = entry["href"]
        try:
            xml_url = _form_xml_url_from_index(index_url)
            if not xml_url:
                log.debug("No form XML found in %s", index_url)
                continue
            xml_bytes = edgar_client.get(xml_url)
            yield from parse_form4_xml(
                xml_bytes,
                accession=entry["accession"],
                source_url=index_url,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Form 4 parse failed accession=%s: %s", entry["accession"], exc)
            continue

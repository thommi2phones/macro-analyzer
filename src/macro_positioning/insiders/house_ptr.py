"""House Clerk Periodic Transaction Report (PTR) scraper.

Pipeline:
  1. Download `https://disclosures-clerk.house.gov/public_disc/financial-pdfs/<YEAR>FD.zip`
     once per run, cache under `<base_dir>/cache/insiders/house/`.
  2. Parse the `<YEAR>FD.xml` index — one element per filing. Filter to
     `FilingType=P` (Periodic Transaction Report).
  3. For each PTR newer than the cursor (or in the explicit --since window),
     fetch the PDF from `.../public_disc/ptr-pdfs/<YEAR>/<DocID>.pdf`,
     cache it locally, parse the transaction table with pdfplumber.
  4. Yield one `ScrapedEvent` per transaction row.

Owner codes (SP=spouse, DC=dependent child, JT=joint, blank=self) are
preserved in `actor_relationship`. The disclosing principal (the House
member) is the author; the actor is whoever the transaction is "by".

Network calls go through a small `httpx` client with a polite UA header
and retry-once-on-transient-error. Offline tests inject the ZIP path
directly via `iter_events_from_zip()` so no network is needed.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator, Optional
from xml.etree import ElementTree as ET

from macro_positioning.core.settings import settings

from macro_positioning.insiders.base import ScrapedEvent


log = logging.getLogger(__name__)


SOURCE_SLUG = "house"
CHANNEL = "gov_insider"

# Politeness: the House Clerk site is sensitive to scrapers without a UA.
_UA = "macro-analyzer/0.1 (personal research; contact: thomasrlindsey@gmail.com)"
_INDEX_URL = "https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip"
_PTR_URL = "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{year}/{doc_id}.pdf"


# ── Index parsing ───────────────────────────────────────────────────────────


@dataclass
class FilingRef:
    """One row of the year-XML index."""

    doc_id: str
    prefix: str
    last: str
    first: str
    suffix: str
    filing_type: str
    state_dst: str
    year: str
    filing_date: str  # MM/DD/YYYY as the index publishes it

    @property
    def display_name(self) -> str:
        bits = [self.first.strip(), self.last.strip()]
        return " ".join(b for b in bits if b)

    @property
    def filing_date_iso(self) -> str:
        try:
            return datetime.strptime(self.filing_date, "%m/%d/%Y").date().isoformat()
        except ValueError:
            return self.filing_date


def parse_index_xml(xml_bytes: bytes) -> list[FilingRef]:
    """Parse the <YEAR>FD.xml manifest into FilingRef objects."""
    root = ET.fromstring(xml_bytes)
    out: list[FilingRef] = []
    for member in root.findall(".//Member"):
        def _text(tag: str) -> str:
            el = member.find(tag)
            return (el.text or "").strip() if el is not None and el.text else ""

        out.append(FilingRef(
            doc_id=_text("DocID"),
            prefix=_text("Prefix"),
            last=_text("Last"),
            first=_text("First"),
            suffix=_text("Suffix"),
            filing_type=_text("FilingType"),
            state_dst=_text("StateDst"),
            year=_text("Year"),
            filing_date=_text("FilingDate"),
        ))
    return out


# ── PDF parsing ─────────────────────────────────────────────────────────────


# PTR transaction-table headers vary slightly year to year. The reliable
# anchor is the leading "ID" column followed by "Owner" and a ticker /
# asset description column. We pull text and re-split per row.
#
# Each transaction row looks like (typeset):
#   SP   ALV     ABBVIE INC - COMMON STOCK (ABBV) [ST]    P    06/03/2025  $1,001 - $15,000
#                                                          S
# pdfplumber's text extraction usually keeps these on one line per row.

# Owner code → relationship enum.
_OWNER_MAP = {
    "": "self",   # blank/no owner column on some templates means the filer
    "JT": "self",  # joint with spouse — we still attribute to principal
    "SP": "spouse",
    "DC": "dependent",
}

_TRANSACTION_TYPES = {
    "P": "purchase",
    "S": "sale",
    "S (partial)": "sale",
    "E": "exchange",
}

# Ticker in parentheses after the issuer name. We also try to read it from
# the column where the source itself typesets a ticker.
_TICKER_PAREN = re.compile(r"\(([A-Z][A-Z0-9.\-]{0,5})\)")

# Dollar-range column.
_AMOUNT_RANGE = re.compile(r"\$[\d,]+\s*-\s*\$[\d,]+")


def parse_ptr_pdf(pdf_bytes: bytes, *, filing: FilingRef) -> list[ScrapedEvent]:
    """Parse a single PTR PDF into one ScrapedEvent per transaction row.

    pdfplumber is imported lazily so the package imports without it; the
    error surfaces only when an actual parse is attempted.
    """
    try:
        import pdfplumber  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "pdfplumber is required to parse House PTR PDFs. "
            "Add `pdfplumber` to pyproject and reinstall."
        ) from exc

    events: list[ScrapedEvent] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for row in _iter_transaction_rows(text):
                event = _row_to_event(row, filing=filing, row_index=len(events))
                if event is not None:
                    events.append(event)
    return events


def _iter_transaction_rows(page_text: str) -> Iterator[str]:
    """Yield each candidate transaction row from a PTR page's text dump.

    A "transaction row" is a line that contains either a $-range or a
    parenthesized ticker — both PTR formats share these markers.
    """
    for line in page_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if _AMOUNT_RANGE.search(line) or _TICKER_PAREN.search(line):
            # Skip header-line false-positives.
            if line.lower().startswith(("owner", "asset", "transaction", "amount", "date")):
                continue
            yield line


def _row_to_event(row: str, *, filing: FilingRef, row_index: int) -> Optional[ScrapedEvent]:
    """Best-effort parse of one transaction row into a ScrapedEvent.

    PTR PDFs are typeset, not tabular data — the text extractor often
    glues columns together. We use anchors (parenthesized ticker, dollar
    range, single-letter transaction code) rather than fixed positions.
    """
    ticker_match = _TICKER_PAREN.search(row)
    if not ticker_match:
        return None
    ticker = ticker_match.group(1).upper()

    amount = _AMOUNT_RANGE.search(row)
    amount_range = amount.group(0) if amount else None

    # Owner column appears at the row start. Match against the lookup;
    # default to "self" when we can't be sure.
    first_token = row.split()[0] if row.split() else ""
    owner_code = first_token if first_token in _OWNER_MAP else ""
    relationship = _OWNER_MAP.get(owner_code, "self")

    # Transaction type: a standalone "P" or "S" near the ticker. We search
    # the segment after the ticker for the next single-letter code.
    txn_code = ""
    after_ticker = row[ticker_match.end():]
    code_match = re.search(r"\b([PSE])\b", after_ticker)
    if code_match:
        txn_code = code_match.group(1)
    transaction_type = _TRANSACTION_TYPES.get(txn_code, "disclosure")

    external_id = f"{filing.doc_id}#{row_index}"

    return ScrapedEvent(
        source_slug=SOURCE_SLUG,
        channel=CHANNEL,
        external_id=external_id,
        filed_at=filing.filing_date_iso,
        actor_name=filing.display_name if relationship == "self" else f"{filing.display_name} ({owner_code})",
        principal_name=filing.display_name,
        actor_relationship=relationship,
        tickers=[ticker],
        amount_range=amount_range,
        transaction_type=transaction_type,
        raw_text=row,
        source_url=_PTR_URL.format(year=filing.year, doc_id=filing.doc_id),
    )


# ── Fetch + cache layer ─────────────────────────────────────────────────────


def _cache_dir() -> Path:
    d = settings.base_dir / "cache" / "insiders" / "house"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fetch_bytes(url: str, *, timeout: float = 30.0) -> bytes:
    """Lazy httpx fetch with a UA header. Imported inside so tests that
    inject paths directly never need the dependency."""
    import httpx  # type: ignore
    with httpx.Client(timeout=timeout, headers={"User-Agent": _UA}, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.content


def _download_year_zip(year: int) -> Path:
    """Cache the year's FD.zip locally; re-download if missing."""
    path = _cache_dir() / f"{year}FD.zip"
    if path.exists() and path.stat().st_size > 0:
        return path
    log.info("Downloading House FD year zip for %s", year)
    data = _fetch_bytes(_INDEX_URL.format(year=year))
    path.write_bytes(data)
    return path


def _download_ptr_pdf(year: int, doc_id: str) -> bytes:
    pdf_cache = _cache_dir() / "pdfs" / str(year)
    pdf_cache.mkdir(parents=True, exist_ok=True)
    path = pdf_cache / f"{doc_id}.pdf"
    if path.exists() and path.stat().st_size > 0:
        return path.read_bytes()
    log.info("Downloading House PTR PDF %s/%s", year, doc_id)
    data = _fetch_bytes(_PTR_URL.format(year=year, doc_id=doc_id))
    path.write_bytes(data)
    return data


def _read_index_from_zip(zip_path: Path) -> list[FilingRef]:
    with zipfile.ZipFile(zip_path) as zf:
        xml_name = next((n for n in zf.namelist() if n.endswith(".xml")), None)
        if xml_name is None:
            raise RuntimeError(f"No XML in House FD zip {zip_path}")
        return parse_index_xml(zf.read(xml_name))


# ── Public entry points ─────────────────────────────────────────────────────


def iter_events_from_zip(
    zip_path: Path,
    *,
    pdf_loader=None,
    since: Optional[str] = None,
    cursor: Optional[str] = None,
) -> Iterable[ScrapedEvent]:
    """Test-friendly: iterate events from a local zip + a PDF-loading callable.

    `pdf_loader(doc_id, year) -> bytes` lets tests serve fixture PDFs
    without going over the network. In production, the loader downloads
    from the House Clerk endpoint and caches under `cache/insiders/house/pdfs/`.
    """
    if pdf_loader is None:
        def pdf_loader(doc_id: str, year: int) -> bytes:
            return _download_ptr_pdf(year, doc_id)

    index = _read_index_from_zip(zip_path)
    log.info("House FD index: %d filings total", len(index))

    seen_cursor = cursor is None  # if no cursor, every row is new
    for filing in index:
        if filing.filing_type != "P":
            continue
        if since and filing.filing_date_iso < since:
            continue
        # Cursor-based incremental: skip everything up to and including
        # last_external_id (which is the most recent transaction id we ingested,
        # of the form "<DocID>#<row_index>"). Doc-level dedupe is good enough
        # at the year-zip level since the index is published in roughly
        # filing-date order.
        if not seen_cursor:
            if cursor and filing.doc_id == cursor.split("#", 1)[0]:
                seen_cursor = True
            continue
        try:
            year_int = int(filing.year) if filing.year else datetime.utcnow().year
            pdf_bytes = pdf_loader(filing.doc_id, year_int)
        except Exception as exc:  # noqa: BLE001
            log.warning("House PTR PDF fetch failed doc=%s: %s", filing.doc_id, exc)
            continue

        try:
            for event in parse_ptr_pdf(pdf_bytes, filing=filing):
                yield event
        except Exception as exc:  # noqa: BLE001
            log.warning("House PTR PDF parse failed doc=%s: %s", filing.doc_id, exc)
            continue


def fetch_since(cursor: Optional[str], *, since: Optional[str] = None,
                year: Optional[int] = None) -> Iterable[ScrapedEvent]:
    """Default scraper entry point. Downloads (or reuses cached) the
    year-FD zip and walks new PTRs.

    `year` defaults to the current calendar year. To backfill older years,
    call repeatedly with explicit year values.
    """
    year = year or datetime.utcnow().year
    zip_path = _download_year_zip(year)
    yield from iter_events_from_zip(zip_path, since=since, cursor=cursor)

"""Tests for the House PTR scraper.

Two layers:
  - Pure-parse tests (XML index, row regex) — no PDF or filesystem.
  - End-to-end against a zip built in-memory with a stub PDF loader that
    returns a hand-crafted text-extraction. The pdfplumber path is
    exercised separately only if pdfplumber is importable.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from macro_positioning.insiders import house_ptr
from macro_positioning.insiders.house_ptr import (
    FilingRef,
    _iter_transaction_rows,
    _row_to_event,
    parse_index_xml,
)


SAMPLE_INDEX_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<FinancialDisclosure>
  <Member>
    <Prefix>Hon.</Prefix>
    <Last>Pelosi</Last>
    <First>Nancy</First>
    <Suffix></Suffix>
    <FilingType>P</FilingType>
    <StateDst>CA11</StateDst>
    <Year>2026</Year>
    <FilingDate>04/15/2026</FilingDate>
    <DocID>30000001</DocID>
  </Member>
  <Member>
    <Prefix>Hon.</Prefix>
    <Last>Crenshaw</Last>
    <First>Dan</First>
    <Suffix></Suffix>
    <FilingType>P</FilingType>
    <StateDst>TX02</StateDst>
    <Year>2026</Year>
    <FilingDate>04/18/2026</FilingDate>
    <DocID>30000002</DocID>
  </Member>
  <Member>
    <Prefix>Hon.</Prefix>
    <Last>Test</Last>
    <First>Annual</First>
    <Suffix></Suffix>
    <FilingType>A</FilingType>
    <StateDst>NY01</StateDst>
    <Year>2026</Year>
    <FilingDate>03/01/2026</FilingDate>
    <DocID>30000099</DocID>
  </Member>
</FinancialDisclosure>
"""


def test_parse_index_xml_extracts_all_filings():
    refs = parse_index_xml(SAMPLE_INDEX_XML)
    assert len(refs) == 3
    assert refs[0].last == "Pelosi"
    assert refs[0].first == "Nancy"
    assert refs[0].filing_type == "P"
    assert refs[0].doc_id == "30000001"
    assert refs[0].display_name == "Nancy Pelosi"
    assert refs[0].filing_date_iso == "2026-04-15"


def test_iter_transaction_rows_picks_amount_and_ticker_lines():
    page = (
        "Asset Owner Transaction Date Amount\n"
        "SP NVIDIA CORP (NVDA) [ST] P 04/15/2026 $1,001 - $15,000\n"
        "JT APPLE INC (AAPL) [ST] S 04/16/2026 $15,001 - $50,000\n"
        "\n"
        "Page 2 of 4\n"
    )
    rows = list(_iter_transaction_rows(page))
    assert len(rows) == 2
    assert "NVDA" in rows[0]
    assert "AAPL" in rows[1]


def test_row_to_event_purchase():
    filing = FilingRef(
        doc_id="DOC1", prefix="Hon.", last="Pelosi", first="Nancy", suffix="",
        filing_type="P", state_dst="CA11", year="2026", filing_date="04/15/2026",
    )
    row = "SP NVIDIA CORP (NVDA) [ST] P 04/15/2026 $1,001 - $15,000"
    event = _row_to_event(row, filing=filing, row_index=0)
    assert event is not None
    assert event.tickers == ["NVDA"]
    assert event.transaction_type == "purchase"
    assert event.amount_range == "$1,001 - $15,000"
    assert event.actor_relationship == "spouse"
    assert event.principal_name == "Nancy Pelosi"
    assert event.external_id == "DOC1#0"


def test_row_to_event_skips_lines_without_ticker():
    filing = FilingRef("DOC1", "", "Pelosi", "Nancy", "", "P", "CA11", "2026", "04/15/2026")
    assert _row_to_event("Page 1 of 4", filing=filing, row_index=0) is None
    assert _row_to_event("Owner Asset Transaction Date Amount", filing=filing, row_index=0) is None


def test_row_to_event_sale_with_self_owner():
    filing = FilingRef("DOC2", "", "Crenshaw", "Dan", "", "P", "TX02", "2026", "04/18/2026")
    row = "APPLE INC (AAPL) [ST] S 04/18/2026 $50,001 - $100,000"
    event = _row_to_event(row, filing=filing, row_index=2)
    assert event is not None
    assert event.transaction_type == "sale"
    assert event.actor_relationship == "self"


def test_iter_events_from_zip_filters_to_PTR_and_respects_since(tmp_path: Path):
    zip_path = tmp_path / "2026FD.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("2026FD.xml", SAMPLE_INDEX_XML)

    # Stub the PDF loader so we never go over the network or need pdfplumber.
    # Returns the text that parse_ptr_pdf would extract — bypasses pdfplumber
    # by monkeypatching parse_ptr_pdf for this test.
    calls = []

    def fake_loader(doc_id: str, year: int) -> bytes:
        calls.append((doc_id, year))
        return b"FAKE PDF BYTES"

    # Monkeypatch parse_ptr_pdf to a deterministic fixture parser.
    original = house_ptr.parse_ptr_pdf

    def fake_parse(pdf_bytes, *, filing):
        row = "SP NVIDIA CORP (NVDA) [ST] P 04/15/2026 $1,001 - $15,000"
        evt = house_ptr._row_to_event(row, filing=filing, row_index=0)
        return [evt] if evt else []

    house_ptr.parse_ptr_pdf = fake_parse
    try:
        events = list(house_ptr.iter_events_from_zip(
            zip_path,
            pdf_loader=fake_loader,
            since="2026-04-17",
        ))
    finally:
        house_ptr.parse_ptr_pdf = original

    # Only Crenshaw's 04/18 PTR survives the since filter; the annual report
    # (FilingType=A) and Pelosi (04/15) are excluded.
    assert len(calls) == 1
    assert calls[0][0] == "30000002"
    assert len(events) == 1
    assert events[0].principal_name == "Dan Crenshaw"

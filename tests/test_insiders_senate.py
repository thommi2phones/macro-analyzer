"""Tests for the Senate PTR mirror parser."""

from __future__ import annotations

from macro_positioning.insiders.senate_ptr import (
    iter_events_from_json,
    record_to_event,
)


SAMPLE = [
    {
        "transaction_date": "11/10/2020",
        "owner": "Spouse",
        "ticker": "BYND",
        "asset_description": "Beyond Meat, Inc.",
        "asset_type": "Stock",
        "type": "Sale (Full)",
        "amount": "$50,001 - $100,000",
        "comment": "--",
        "senator": "Ron L Wyden",
        "ptr_link": "https://efdsearch.senate.gov/search/view/ptr/a0010f4a-c31a-4824-8b6d-6399b3ccb6f0/",
    },
    {
        "transaction_date": "11/16/2020",
        "owner": "Self",
        "ticker": "BA",
        "asset_description": "The Boeing Company",
        "asset_type": "Stock",
        "type": "Purchase",
        "amount": "$15,001 - $50,000",
        "comment": "R",
        "senator": "Pat Roberts",
        "ptr_link": "https://efdsearch.senate.gov/search/view/ptr/b7e581e7-f154-4dc7-890d-1c827c88ba7a/",
    },
    {
        # Non-equity, should be dropped.
        "transaction_date": "11/17/2020",
        "owner": "Self",
        "ticker": "--",
        "asset_description": "Some Bond",
        "asset_type": "Other",
        "type": "Purchase",
        "amount": "$1,001 - $15,000",
        "comment": "",
        "senator": "Pat Roberts",
        "ptr_link": "",
    },
]


def test_record_to_event_spouse_sale():
    evt = record_to_event(SAMPLE[0], row_index=0)
    assert evt is not None
    assert evt.tickers == ["BYND"]
    assert evt.transaction_type == "sale"
    assert evt.actor_relationship == "spouse"
    assert evt.principal_name == "Ron L Wyden"
    assert "a0010f4a" in evt.external_id


def test_record_to_event_drops_non_equity():
    assert record_to_event(SAMPLE[2], row_index=2) is None


def test_iter_events_filters_by_since():
    out = list(iter_events_from_json(SAMPLE, since="2020-11-15"))
    # Only the Boeing/self-purchase remains (2020-11-16 ≥ 2020-11-15);
    # Wyden's 11/10 is before the cutoff and the bond row is dropped.
    assert len(out) == 1
    assert out[0].tickers == ["BA"]
    assert out[0].transaction_type == "purchase"
    assert out[0].actor_relationship == "self"

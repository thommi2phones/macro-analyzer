"""Tests for the insiders shared base layer: ScrapedEvent helpers,
cursor table, and the ingest funnel against a real SQLite DB.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from macro_positioning.core.settings import settings
from macro_positioning.db.schema import initialize_database
from macro_positioning.insiders import base, ingest
from macro_positioning.insiders.base import ScrapedEvent


@pytest.fixture
def db(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "insiders.db"
    initialize_database(db_path)
    monkeypatch.setattr(settings, "base_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "sqlite:///insiders.db")
    return db_path


def _event(**overrides) -> ScrapedEvent:
    base_evt = dict(
        source_slug="house",
        channel="gov_insider",
        external_id="EVT-1",
        filed_at="2026-05-01",
        actor_name="Nancy Pelosi",
        principal_name="Nancy Pelosi",
        actor_relationship="self",
        tickers=["NVDA"],
        amount_range="$1,001 - $15,000",
        transaction_type="purchase",
        raw_text="SP NVDA NVIDIA CORP (NVDA) P 04/15/2026 $1,001 - $15,000",
        source_url="https://example.test/ptr/1.pdf",
    )
    base_evt.update(overrides)
    return ScrapedEvent(**base_evt)


def test_cursor_roundtrip(db):
    assert base.get_cursor("house") is None
    base.set_cursor("house", "DOC123#7", status="ok")
    assert base.get_cursor("house") == "DOC123#7"
    rows = base.list_cursors()
    assert rows and rows[0]["source_slug"] == "house"
    assert rows[0]["last_run_status"] == "ok"


def test_infer_side_buy_vs_sell():
    assert _event(transaction_type="purchase").infer_side() == "LONG"
    assert _event(transaction_type="sale").infer_side() == "WATCH"
    assert _event(transaction_type=None).infer_side() is None


def test_funnel_writes_document_and_author(db):
    import sqlite3

    summary = ingest.funnel([_event()], source_slug="house")
    assert summary["ingested"] == 1
    assert summary["errors"] == []

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        author = conn.execute(
            "SELECT author_id, display_name, channel FROM input_authors "
            "WHERE channel='gov_insider'"
        ).fetchone()
        assert author is not None
        assert author["display_name"] == "Nancy Pelosi"
        # slug format: {channel}:{display}
        assert author["author_id"] == "gov-insider:nancy-pelosi"

        doc = conn.execute(
            "SELECT source_id, author_id, raw_text, user_metadata_json, tags_json "
            "FROM documents WHERE author_id=?",
            (author["author_id"],),
        ).fetchone()
        assert doc is not None
        assert doc["source_id"] == f"manual:{author['author_id']}"
        assert "$NVDA" in doc["raw_text"] or "NVDA" in doc["raw_text"]
        # cursor should now point at the event we ingested
        assert base.get_cursor("house") == "EVT-1"


def test_funnel_related_party_preserved_in_metadata(db):
    """A spouse-held PTR attributes to the principal but tags the actor."""
    import json
    import sqlite3

    event = _event(
        external_id="EVT-2",
        actor_name="Paul Pelosi (SP)",
        actor_relationship="spouse",
    )
    ingest.funnel([event], source_slug="house")

    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT raw_text FROM documents ORDER BY ingested_at DESC LIMIT 1"
        ).fetchone()
        # The composed body explicitly names the actor + relationship so
        # the dashboard can show "held by spouse" downstream.
        assert "Paul Pelosi" in row[0]
        assert "spouse" in row[0]


def test_funnel_skips_bad_event_does_not_kill_run(db, monkeypatch):
    """One bad event must not abort the rest of the batch."""
    from macro_positioning.manual import processor

    real_ingest = processor.ingest
    calls = {"n": 0}

    def flaky(payload):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("synthetic")
        return real_ingest(payload)

    monkeypatch.setattr(processor, "ingest", flaky)

    summary = ingest.funnel(
        [_event(external_id="A"), _event(external_id="B")],
        source_slug="house",
    )
    assert summary["ingested"] == 1
    assert summary["skipped"] == 1
    assert summary["errors"]

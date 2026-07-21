"""Schema + Signal model basics."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from macro_positioning.core.settings import settings
from macro_positioning.db.schema import initialize_database
from macro_positioning.signals import repository
from macro_positioning.signals.base import (
    Signal,
    SignalCatalystType,
    SignalHorizon,
    SignalSide,
    SignalStatus,
)


@pytest.fixture
def db(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "signals.db"
    initialize_database(db_path)
    monkeypatch.setattr(settings, "base_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "sqlite:///signals.db")
    return db_path


def test_signals_table_created(db):
    with sqlite3.connect(db) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(signals)")}
    # Spot-check a representative spread of columns
    expected = {
        "signal_id", "document_id", "extracted_at", "extraction_run_id",
        "asset_ticker", "asset_class", "side", "conviction",
        "horizon", "horizon_days", "entry_zone_low", "stop_loss",
        "target_1", "thesis_tags_json", "catalyst_type", "source_slug",
        "author_id", "author_trust_weight", "extractor_name",
        "extractor_version", "model_provider", "extraction_call_id",
        "status", "expires_at", "weighted_score", "cost_usd",
    }
    missing = expected - cols
    assert not missing, f"missing columns: {missing}"


def test_attempts_table_created(db):
    with sqlite3.connect(db) as conn:
        cols = {row[1] for row in conn.execute(
            "PRAGMA table_info(signal_extraction_attempts)")}
    assert {"attempt_id", "document_id", "status", "signals_produced"} <= cols


def test_signal_side_coerce():
    assert SignalSide.coerce("buy") == SignalSide.LONG
    assert SignalSide.coerce("BUY") == SignalSide.LONG
    assert SignalSide.coerce("sell") == SignalSide.SHORT
    assert SignalSide.coerce("exited") == SignalSide.EXIT
    assert SignalSide.coerce(None) == SignalSide.WATCH
    assert SignalSide.coerce("garbage") == SignalSide.WATCH


def test_signal_horizon_from_days():
    assert SignalHorizon.from_days(0) == SignalHorizon.INTRADAY
    assert SignalHorizon.from_days(7) == SignalHorizon.SWING
    assert SignalHorizon.from_days(60) == SignalHorizon.POSITION
    assert SignalHorizon.from_days(500) == SignalHorizon.STRATEGIC
    assert SignalHorizon.from_days(None) is None


def test_signal_conviction_bounded():
    s = Signal(
        document_id="d1", asset_ticker="aapl",
        source_slug="manual", extractor_name="t",
        conviction=99.0,
    )
    assert s.conviction == 5.0
    assert s.asset_ticker == "AAPL"


def test_compute_weighted_score():
    s = Signal(
        document_id="d1", asset_ticker="NVDA", source_slug="form4",
        extractor_name="insider_extractor",
        conviction=4.0, source_trust_weight=1.5, author_trust_weight=1.2,
    )
    assert s.compute_weighted_score() == pytest.approx(4.0 * 1.5 * 1.2)


def test_insert_and_read_signal(db, monkeypatch):
    # documents row first (FK)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO documents (document_id, source_id, title, "
            "published_at, content_type, raw_text, cleaned_text, "
            "tags_json, ingested_at) VALUES (?,?,?,?,?,?,?,?,?)",
            ("doc-1", "manual:test", "t", "2026-06-01", "manual_note",
             "raw", "clean", "{}", "2026-06-01"),
        )
        conn.commit()

    s = Signal(
        document_id="doc-1", asset_ticker="AAPL",
        source_slug="manual", extractor_name="insider_extractor",
        side=SignalSide.LONG, conviction=3.5,
        thesis_tags=["fed_pivot"],
        catalyst_type=SignalCatalystType.MACRO_PRINT,
        horizon=SignalHorizon.SWING,
    )
    sid = repository.insert_signal(s, db_path=db)
    assert sid == s.signal_id

    rows = repository.load_active_signals_for_ticker("AAPL", db_path=db)
    assert len(rows) == 1
    assert rows[0]["asset_ticker"] == "AAPL"
    assert rows[0]["side"] == "LONG"
    assert rows[0]["conviction"] == 3.5
    assert rows[0]["thesis_tags_json"] is not None

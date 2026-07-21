"""Inline extraction path for self-authored manual drops.

is_self_authored=True → processor.ingest runs signal extraction inline
and returns the previews in IngestResponse.signals. Other drops batch.
Extractor errors must never break ingest.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from macro_positioning.core.settings import settings
from macro_positioning.db.schema import initialize_database
from macro_positioning.manual import processor
from macro_positioning.manual.models import AuthorRef, ManualInputPayload, ManualMetadata


@pytest.fixture
def db(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "inline.db"
    initialize_database(db_path)
    monkeypatch.setattr(settings, "base_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "sqlite:///inline.db")
    return db_path


def _payload(*, self_authored: bool = False, text="$AAPL long here, earnings catalyst") -> ManualInputPayload:
    return ManualInputPayload(
        text=text,
        metadata=ManualMetadata(ticker="AAPL", side="LONG", conviction=3),
        author=AuthorRef(display_name="Me", channel="self", channel_type="self"),
        is_self_authored=self_authored,
    )


# Fake LLM result the brain backends would return.
def _fake_llm_signal_payload():
    return {
        "signals": [{
            "asset_ticker": "AAPL",
            "asset_class": "equity",
            "side": "LONG",
            "conviction": 4.0,
            "horizon": "swing",
            "thesis_summary": "earnings beat",
            "catalyst_type": "earnings",
            "extractor_confidence": 0.85,
            "raw_excerpt": "long AAPL into earnings",
        }],
        "no_signal_reason": None,
    }


def _install_fake_backend(monkeypatch, *, raise_exc: Exception | None = None,
                          payload: dict | None = None):
    class FakeBackendResult:
        text = json.dumps(payload or _fake_llm_signal_payload())
        model = "gemini-2.5-pro"
        latency_ms = 50.0
        input_tokens = 600
        output_tokens = 80
        cost_usd = 0.0019

    def fake_generate(*a, **k):
        if raise_exc is not None:
            raise raise_exc
        return FakeBackendResult()

    monkeypatch.setattr(
        "macro_positioning.signals.llm_extractor.generate",
        fake_generate,
    )
    monkeypatch.setattr(settings, "brain_primary_backend", "gemini", raising=False)


# ── Tests ──────────────────────────────────────────────────────────────────


def test_self_authored_runs_inline_and_returns_signals(db, monkeypatch):
    _install_fake_backend(monkeypatch)
    resp = processor.ingest(_payload(self_authored=True))
    assert resp.signals, "self-authored should return inline signal previews"
    assert resp.signals[0]["asset_ticker"] == "AAPL"
    assert resp.signals[0]["side"] == "LONG"
    assert resp.inline_extraction_error is None

    # Persisted to signals table
    with sqlite3.connect(db) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM signals WHERE document_id=?",
            (resp.document_id,),
        ).fetchone()[0]
    assert n == 1


def test_default_path_skips_inline_extraction(db, monkeypatch):
    # Even if a backend is configured, plain drops shouldn't trigger extraction.
    _install_fake_backend(monkeypatch)
    resp = processor.ingest(_payload(self_authored=False))
    assert resp.signals == []
    assert resp.inline_extraction_error is None

    with sqlite3.connect(db) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM signals WHERE document_id=?",
            (resp.document_id,),
        ).fetchone()[0]
    assert n == 0


def test_inline_extraction_error_falls_through_cleanly(db, monkeypatch):
    _install_fake_backend(monkeypatch, raise_exc=RuntimeError("Gemini 503"))
    resp = processor.ingest(_payload(self_authored=True))
    # Ingest must succeed
    assert resp.document_id
    # No signals written
    assert resp.signals == []
    # Error surfaced for the SPA, but doc itself persisted
    assert resp.inline_extraction_error is not None
    with sqlite3.connect(db) as conn:
        ndocs = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE document_id=?",
            (resp.document_id,),
        ).fetchone()[0]
    assert ndocs == 1


def test_inline_path_still_queues_doc_when_extractor_returned_no_signal(db, monkeypatch):
    # Backend responds with "no signal" — still success, but no row written.
    _install_fake_backend(monkeypatch, payload={"signals": [],
                                                "no_signal_reason": "nothing actionable"})
    resp = processor.ingest(_payload(self_authored=True,
                                     text="random ramble no ticker no thesis"))
    assert resp.signals == []
    # attempt was logged so batch path won't re-process needlessly
    with sqlite3.connect(db) as conn:
        n_attempts = conn.execute(
            """SELECT COUNT(*) FROM signal_extraction_attempts
               WHERE document_id=? AND status IN ('success','no_signal')""",
            (resp.document_id,),
        ).fetchone()[0]
    assert n_attempts >= 1

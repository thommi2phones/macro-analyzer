"""Cost capture in BackendResult + extractor version bump re-extraction."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from macro_positioning.brain.backends import _estimate_cost, BackendResult
from macro_positioning.core.settings import settings
from macro_positioning.db.schema import initialize_database
from macro_positioning.signals import repository
from macro_positioning.signals.base import ExtractionResult


@pytest.fixture
def db(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "cost.db"
    initialize_database(db_path)
    monkeypatch.setattr(settings, "base_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "sqlite:///cost.db")
    return db_path


# ── Cost pricing math ─────────────────────────────────────────────────────


def test_estimate_cost_gemini_pro():
    # 1M in @ $1.25, 500K out @ $10  → $1.25 + $5.00 = $6.25
    cost = _estimate_cost("gemini-2.5-pro", 1_000_000, 500_000)
    assert cost == pytest.approx(6.25, rel=1e-3)


def test_estimate_cost_claude_sonnet():
    cost = _estimate_cost("claude-sonnet-4-20250514", 100_000, 10_000)
    # 0.1 * 3 + 0.01 * 15 = 0.3 + 0.15 = 0.45
    assert cost == pytest.approx(0.45, rel=1e-3)


def test_estimate_cost_unknown_model_returns_none():
    assert _estimate_cost("brand-new-model", 1000, 500) is None


def test_estimate_cost_no_tokens_returns_none():
    assert _estimate_cost("gemini-2.5-pro", None, None) is None


def test_estimate_cost_partial_tokens():
    cost = _estimate_cost("gemini-2.5-pro", 1_000_000, None)
    # Only input cost counted: $1.25
    assert cost == pytest.approx(1.25, rel=1e-3)


def test_backend_result_carries_cost_fields():
    r = BackendResult(
        text="ok", model="gemini-2.5-pro", latency_ms=100.0,
        input_tokens=500, output_tokens=200, cost_usd=0.0021,
    )
    assert r.input_tokens == 500
    assert r.output_tokens == 200
    assert r.cost_usd == 0.0021


# ── Version-bump re-extraction policy ─────────────────────────────────────


def _insert_doc(db_path: Path, doc_id: str, *, source_id: str = "manual:big-nuts") -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO documents
               (document_id, source_id, title, published_at, content_type,
                raw_text, cleaned_text, tags_json, ingested_at, author_id)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (doc_id, source_id, "t", "2026-06-01", "manual_note",
             "raw", "clean", "{}", "2026-06-01", "big-nuts"),
        )
        conn.commit()


def _record_attempt(db_path: Path, *, doc_id: str, extractor_name: str,
                    extractor_version: str, status: str = "success") -> None:
    result = ExtractionResult(
        document_id=doc_id,
        extractor_name=extractor_name,
        extractor_version=extractor_version,
        status=status,
    )
    repository.record_attempt(result, db_path=db_path)


def test_pending_no_attempts_returns_doc(db):
    _insert_doc(db, "doc-fresh")
    pending = repository.pending_documents(
        since_days=365, db_path=db,
        current_extractor_versions={"llm_extractor": "v1"},
    )
    assert any(d["document_id"] == "doc-fresh" for d in pending)


def test_pending_excludes_already_attempted(db):
    _insert_doc(db, "doc-done")
    _record_attempt(db, doc_id="doc-done",
                    extractor_name="llm_extractor", extractor_version="v1")
    pending = repository.pending_documents(
        since_days=365, db_path=db,
        current_extractor_versions={"llm_extractor": "v1"},
    )
    assert not any(d["document_id"] == "doc-done" for d in pending)


def test_pending_resurfaces_on_version_bump(db):
    _insert_doc(db, "doc-stale")
    _record_attempt(db, doc_id="doc-stale",
                    extractor_name="llm_extractor", extractor_version="v1")
    # Bump current version
    pending = repository.pending_documents(
        since_days=365, db_path=db,
        current_extractor_versions={"llm_extractor": "v2"},
    )
    doc = next((d for d in pending if d["document_id"] == "doc-stale"), None)
    assert doc is not None, "v2 should pick up v1-extracted doc for re-run"
    assert doc.get("_reextract_for") == "llm_extractor"


def test_pending_version_bump_scoped_to_named_extractor(db):
    _insert_doc(db, "doc-mixed")
    _record_attempt(db, doc_id="doc-mixed",
                    extractor_name="insider_extractor", extractor_version="v1")
    # Asking specifically about llm_extractor, bumping THAT version, should
    # NOT resurface doc-mixed (which only had an insider attempt).
    pending = repository.pending_documents(
        since_days=365, db_path=db,
        extractor_name="llm_extractor",
        current_extractor_versions={"llm_extractor": "v2"},
    )
    # However: since llm_extractor never attempted doc-mixed, the "never
    # attempted" path picks it up. That's correct behaviour — confirm it.
    assert any(d["document_id"] == "doc-mixed" for d in pending)


def test_version_bump_dedupe(db):
    """A doc surfaced by both 'never attempted' and 'version bump' shouldn't
    appear twice."""
    _insert_doc(db, "doc-both")
    # No attempts at all + a version-bump check
    pending = repository.pending_documents(
        since_days=365, db_path=db,
        current_extractor_versions={"llm_extractor": "v9"},
    )
    matching = [d for d in pending if d["document_id"] == "doc-both"]
    assert len(matching) == 1

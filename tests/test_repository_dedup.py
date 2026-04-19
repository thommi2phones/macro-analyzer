"""Dedup behavior of SQLiteRepository.save_document()."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from macro_positioning.core.models import NormalizedDocument
from macro_positioning.db.repository import SQLiteRepository
from macro_positioning.db.schema import initialize_database


def _doc(document_id: str, source_id: str, url: str | None, title: str = "t") -> NormalizedDocument:
    return NormalizedDocument(
        document_id=document_id,
        source_id=source_id,
        title=title,
        url=url,
        published_at=datetime.now(UTC),
        author=None,
        content_type="article",
        raw_text="body",
        cleaned_text="body",
        tags=[],
    )


def test_insert_returns_true_first_time(tmp_path: Path):
    db = tmp_path / "t.db"
    initialize_database(db)
    repo = SQLiteRepository(db)
    assert repo.save_document(_doc("abc", "src", "https://x/1")) is True


def test_duplicate_primary_key_returns_false(tmp_path: Path):
    db = tmp_path / "t.db"
    initialize_database(db)
    repo = SQLiteRepository(db)
    repo.save_document(_doc("abc", "src", "https://x/1"))
    # Same document_id — INSERT OR IGNORE skips
    assert repo.save_document(_doc("abc", "src", "https://x/1")) is False


def test_duplicate_source_url_returns_false(tmp_path: Path):
    db = tmp_path / "t.db"
    initialize_database(db)
    repo = SQLiteRepository(db)
    repo.save_document(_doc("id-1", "finnhub_aapl", "https://example.com/a"))
    # Different document_id but same (source_id, url) — blocked by unique index
    result = repo.save_document(_doc("id-2", "finnhub_aapl", "https://example.com/a"))
    assert result is False


def test_distinct_url_inserts(tmp_path: Path):
    db = tmp_path / "t.db"
    initialize_database(db)
    repo = SQLiteRepository(db)
    repo.save_document(_doc("id-1", "finnhub_aapl", "https://example.com/a"))
    assert repo.save_document(_doc("id-2", "finnhub_aapl", "https://example.com/b")) is True


def test_null_url_does_not_collide(tmp_path: Path):
    """Docs without URLs dedupe only via their PK, not the (source, NULL) index."""
    db = tmp_path / "t.db"
    initialize_database(db)
    repo = SQLiteRepository(db)
    assert repo.save_document(_doc("id-1", "src", None)) is True
    assert repo.save_document(_doc("id-2", "src", None)) is True

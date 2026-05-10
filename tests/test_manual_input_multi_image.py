"""End-to-end tests for the manual-input ingest path with multiple images.

Drives processor.ingest() against a real SQLite DB and asserts that:
  - attachment_paths_json stores the full ordered list,
  - attachment_path stores the first path (back-compat),
  - list_recent_inputs() hydrates attachment_paths,
  - older single-image rows still surface a one-element list.
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
    db_path = tmp_path / "manual.db"
    initialize_database(db_path)
    # `sqlite_path` is a derived property on Settings — point base_dir +
    # database_url at the temp file so the property resolves to it.
    monkeypatch.setattr(settings, "base_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "sqlite:///manual.db")
    return db_path


def _payload(paths: list[str]) -> ManualInputPayload:
    return ManualInputPayload(
        text="$BTC breakout retest, multi-timeframe view",
        metadata=ManualMetadata(ticker="BTC", side="LONG", conviction=4, timeframe="4H"),
        author=AuthorRef(display_name="Capo", channel="BWatch chat", channel_type="telegram"),
        attachment_paths=paths,
    )


def test_ingest_persists_full_path_list(db: Path):
    paths = [
        "uploads/charts/2026-05/aaa.png",
        "uploads/charts/2026-05/bbb.png",
        "uploads/charts/2026-05/ccc.png",
    ]
    res = processor.ingest(_payload(paths))
    assert res.pending_vision is True

    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT attachment_path, attachment_paths_json FROM documents WHERE document_id = ?",
            (res.document_id,),
        ).fetchone()
    assert row[0] == paths[0]
    assert json.loads(row[1]) == paths


def test_list_recent_inputs_hydrates_paths(db: Path):
    paths = ["uploads/charts/2026-05/x.png", "uploads/charts/2026-05/y.png"]
    processor.ingest(_payload(paths))

    history = processor.list_recent_inputs(limit=10)
    assert len(history) == 1
    assert history[0]["attachment_paths"] == paths
    assert history[0]["attachment_path"] == paths[0]


def test_legacy_single_path_still_works(db: Path):
    payload = ManualInputPayload(
        text="single image, old API surface",
        metadata=ManualMetadata(ticker="ETH", side="LONG"),
        author=AuthorRef(display_name="self", channel="self", channel_type="self"),
        attachment_path="uploads/charts/2026-05/legacy.png",
    )
    res = processor.ingest(payload)
    history = processor.list_recent_inputs(limit=10)
    assert history[0]["attachment_paths"] == ["uploads/charts/2026-05/legacy.png"]
    assert res.pending_vision is True


def test_ingest_without_image_clears_pending_vision(db: Path):
    payload = ManualInputPayload(
        text="just a note",
        author=AuthorRef(display_name="self", channel="self", channel_type="self"),
    )
    res = processor.ingest(payload)
    assert res.pending_vision is False
    history = processor.list_recent_inputs(limit=10)
    assert history[0]["attachment_paths"] == []
    assert history[0]["attachment_path"] is None

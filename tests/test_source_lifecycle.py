"""Tests for ingestion/source_lifecycle.py.

Uses an isolated temp sources.json so tests don't mutate the real
config/sources.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def isolated_registry(tmp_path, monkeypatch):
    """Point source_lifecycle at a tmp sources.json with two seed records."""
    fake = tmp_path / "sources.json"
    fake.write_text(
        json.dumps(
            {
                "$schema_version": "1.0",
                "sources": [
                    {
                        "source_id": "seed_active",
                        "name": "Seed Active",
                        "source_type": "newsletter",
                        "priority": "core",
                        "trust_weight": 0.8,
                        "routing_tags": ["macro", "rates"],
                        "onboarded_at": "2026-01-01",
                    },
                    {
                        "source_id": "seed_archived",
                        "name": "Seed Archived",
                        "source_type": "newsletter",
                        "priority": "archived",
                        "trust_weight": 0.3,
                        "routing_tags": ["equities"],
                        "onboarded_at": "2025-06-01",
                        "archived_at": "2026-04-01",
                    },
                ],
            }
        )
    )
    # Module-level constant — patch it before each call
    import macro_positioning.ingestion.source_lifecycle as sl
    monkeypatch.setattr(sl, "SOURCES_PATH", fake)
    yield sl


def test_load_active_only_by_default(isolated_registry):
    sl = isolated_registry
    rows = sl.load_sources()
    ids = [r.source_id for r in rows]
    assert "seed_active" in ids
    assert "seed_archived" not in ids


def test_load_with_archived(isolated_registry):
    sl = isolated_registry
    rows = sl.load_sources(include_archived=True)
    assert len(rows) == 2


def test_get_source_finds_archived(isolated_registry):
    sl = isolated_registry
    rec = sl.get_source("seed_archived")
    assert rec is not None
    assert rec.archived_at == "2026-04-01"


def test_get_source_missing_returns_none(isolated_registry):
    assert isolated_registry.get_source("nope") is None


def test_add_source_persists(isolated_registry):
    sl = isolated_registry
    rec = sl.add_source(
        "new_source",
        name="New Source",
        source_type="newsletter",
        routing_tags=["macro"],
    )
    assert rec.priority == "trial"  # default
    assert rec.trust_weight == 0.5  # default
    # Round-trip
    assert sl.get_source("new_source") is not None
    rows = sl.load_sources()
    assert any(r.source_id == "new_source" for r in rows)


def test_add_source_duplicate_raises(isolated_registry):
    with pytest.raises(ValueError):
        isolated_registry.add_source(
            "seed_active",
            name="dup",
            source_type="newsletter",
        )


def test_archive_sets_priority_and_date(isolated_registry):
    sl = isolated_registry
    rec = sl.archive_source("seed_active")
    assert rec.priority == "archived"
    assert rec.archived_at is not None
    # Now excluded from default load
    ids = [r.source_id for r in sl.load_sources()]
    assert "seed_active" not in ids


def test_archive_missing_raises(isolated_registry):
    with pytest.raises(KeyError):
        isolated_registry.archive_source("nope")


def test_unarchive_restores(isolated_registry):
    sl = isolated_registry
    rec = sl.unarchive_source("seed_archived", new_priority="secondary")
    assert rec.archived_at is None
    assert rec.priority == "secondary"
    ids = [r.source_id for r in sl.load_sources()]
    assert "seed_archived" in ids


def test_promote_changes_priority(isolated_registry):
    sl = isolated_registry
    rec = sl.promote_source("seed_active", "secondary")
    assert rec.priority == "secondary"


def test_promote_to_archived_sets_date(isolated_registry):
    sl = isolated_registry
    rec = sl.promote_source("seed_active", "archived")
    assert rec.archived_at is not None


def test_promote_invalid_priority(isolated_registry):
    with pytest.raises(ValueError):
        isolated_registry.promote_source("seed_active", "supercharged")


def test_retag_add_and_remove(isolated_registry):
    sl = isolated_registry
    rec = sl.retag_source("seed_active", add=["liquidity"], remove=["rates"])
    assert "liquidity" in rec.routing_tags
    assert "rates" not in rec.routing_tags
    assert "macro" in rec.routing_tags  # untouched


def test_count_by_priority(isolated_registry):
    counts = isolated_registry.count_by_priority()
    assert counts.get("core") == 1
    assert counts.get("archived") == 1


def test_summarize_returns_compact_view(isolated_registry):
    rows = isolated_registry.summarize_sources()
    assert all(hasattr(r, "trust_weight") for r in rows)
    assert all(hasattr(r, "routing_tags") for r in rows)

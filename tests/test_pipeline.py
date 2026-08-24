"""End-to-end pipeline: ingest → synthesis → validate → memo.

This test used to call `build_pipeline()`, which does
`initialize_database(settings.sqlite_path)` and `build_brain_client()` —
i.e. it ran against the *production* database and whichever real LLM
backend the local .env had configured. On 2026-08-24 that was traced as
part of why `pytest tests/` held the live DB open read-write and took
tens of minutes instead of seconds.

The pipeline takes its repository and brain by injection precisely so
this doesn't have to happen. Both are now explicit: a temp DB, and the
heuristic (no-network, deterministic) brain client.

Two settings still have to be redirected, because `run()` reaches for
them itself rather than taking them as arguments:

  fred_api_key — `_build_market_provider` uses the live FRED provider
    whenever a key is configured, so with a real .env this test spent
    ~21s on network calls. Blank forces the static provider, which reads
    the observations `sample_context()` already supplies.
  base_dir — `write_outputs` writes the rendered memo to
    `base_dir/data/processed/latest_memo.md`, so every run overwrote a
    file in the working repo.
"""
from __future__ import annotations

import pytest

from macro_positioning.brain.client import HeuristicBrainClient
from macro_positioning.core.settings import settings
from macro_positioning.db.repository import SQLiteRepository
from macro_positioning.db.schema import initialize_database
from macro_positioning.ingestion.sample_sources import sample_context, sample_documents
from macro_positioning.pipelines.run_pipeline import PositioningPipeline


@pytest.fixture
def offline(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "fred_api_key", "")
    monkeypatch.setattr(settings, "base_dir", tmp_path)
    (tmp_path / "data" / "processed").mkdir(parents=True, exist_ok=True)


def test_pipeline_generates_memo(tmp_path, offline):
    db_path = tmp_path / "pipeline.db"
    initialize_database(db_path)

    pipeline = PositioningPipeline(
        repository=SQLiteRepository(db_path),
        brain=HeuristicBrainClient(),
        source_weights={},
    )
    result = pipeline.run(sample_documents(), context=sample_context())

    assert result.documents_ingested == 3
    assert result.theses_extracted >= 1
    assert result.validated_theses >= 1
    assert result.memo_id

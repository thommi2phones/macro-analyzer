"""Tests for the ingestion scheduler (jobs wired but not executing on cron)."""
from __future__ import annotations

import pytest

from macro_positioning.ingestion import scheduler


class _FakePipeline:
    def __init__(self):
        self.called_with = None

    def run(self, docs):
        self.called_with = docs
        from macro_positioning.core.models import PipelineRunResult
        return PipelineRunResult(
            documents_ingested=len(docs),
            theses_extracted=0,
            memo_id="memo-test",
        )


def test_morning_run_wires_gmail_google_pipeline(monkeypatch):
    from macro_positioning.ingestion import personal_gmail, google_news_rss

    monkeypatch.setattr(
        personal_gmail,
        "fetch_and_persist",
        lambda days=2: {"fetched": 3, "new_documents": 3, "duplicates_skipped": 0, "sources": {}},
    )
    monkeypatch.setattr(
        google_news_rss,
        "fetch_all_macro_topics",
        lambda max_items_per_topic=10: [],
    )
    fake = _FakePipeline()
    monkeypatch.setattr(scheduler, "build_pipeline", lambda: fake)

    summary = scheduler.morning_run()

    assert summary["steps"]["gmail"]["status"] == "ok"
    assert summary["steps"]["google_news"]["status"] == "ok"
    assert summary["steps"]["pipeline"]["status"] == "ok"
    assert summary["steps"]["pipeline"]["memo_id"] == "memo-test"
    assert "duration_seconds" in summary


def test_morning_run_survives_gmail_failure(monkeypatch):
    from macro_positioning.ingestion import personal_gmail, google_news_rss

    def boom(**_):
        raise RuntimeError("gmail auth broken")
    monkeypatch.setattr(personal_gmail, "fetch_and_persist", boom)
    monkeypatch.setattr(
        google_news_rss,
        "fetch_all_macro_topics",
        lambda max_items_per_topic=10: [],
    )
    monkeypatch.setattr(scheduler, "build_pipeline", lambda: _FakePipeline())

    summary = scheduler.morning_run()

    assert summary["steps"]["gmail"]["status"] == "error"
    # Other steps still run
    assert summary["steps"]["google_news"]["status"] == "ok"
    assert summary["steps"]["pipeline"]["status"] == "ok"


def test_midday_refresh_runs(monkeypatch):
    from macro_positioning.ingestion import google_news_rss
    monkeypatch.setattr(
        google_news_rss,
        "fetch_all_macro_topics",
        lambda max_items_per_topic=5: [],
    )
    summary = scheduler.midday_refresh()
    assert summary["steps"]["google_news"]["status"] == "ok"


def test_run_cron_raises_if_apscheduler_missing(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "apscheduler.schedulers.blocking":
            raise ImportError("fake")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match="apscheduler"):
        scheduler.run_cron()


def test_safe_wrapper_absorbs_exceptions():
    def boom():
        raise ValueError("explode")
    wrapped = scheduler._safe(boom)
    # Should not raise
    wrapped()

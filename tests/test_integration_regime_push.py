"""Tests for the regime-change push loop + view-cache invalidation."""
from __future__ import annotations

import pytest

from macro_positioning.core.models import Thesis, ThesisStatus, ViewDirection
from macro_positioning.integration import regime_watch


def _make_thesis(thesis_id: str, theme: str, direction: str, confidence: float = 0.8) -> Thesis:
    return Thesis(
        thesis_id=thesis_id,
        thesis=f"Test thesis {thesis_id}",
        theme=theme,
        horizon="2-12 weeks",
        direction=ViewDirection(direction),
        assets=[theme],
        confidence=confidence,
        status=ThesisStatus.active,
        source_ids=["test_source"],
    )


class _FakeMemo:
    def __init__(self, summary: str):
        self.summary = summary


def test_snapshot_from_theses_picks_highest_conf_per_theme():
    theses = [
        _make_thesis("t1", "inflation", "bullish", 0.6),
        _make_thesis("t2", "inflation", "bearish", 0.9),  # should win
        _make_thesis("t3", "equities", "bullish", 0.7),
    ]
    memo = _FakeMemo("Stagflation regime")
    snap = regime_watch.snapshot_from_theses_and_memo(theses, memo)
    assert snap.directional_bias == {"inflation": "bearish", "equities": "bullish"}
    assert snap.regime == "Stagflation regime"
    # top_theses includes both themes' winners
    assert "t2" in snap.top_theses
    assert "t3" in snap.top_theses


def test_detect_and_push_no_change_returns_changed_false(monkeypatch, tmp_path):
    # Point SQLite at a temp DB so we start with no prior snapshots.
    from macro_positioning.core.settings import settings
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/test.db")
    # Neither: clear tactical webhook so push is a no-op if triggered
    monkeypatch.setattr(settings, "tactical_webhook_url", "")

    theses = [_make_thesis("t1", "inflation", "bullish")]
    memo = _FakeMemo("Initial regime")

    first = regime_watch.detect_and_push(theses, memo)
    assert first["changed"] is True  # first snapshot always "changes"
    assert first["pushed"] is False  # no webhook url

    # Re-running with same inputs → no change
    second = regime_watch.detect_and_push(theses, memo)
    assert second["changed"] is False


def test_detect_and_push_fires_webhook_when_url_set(monkeypatch, tmp_path):
    from macro_positioning.core.settings import settings
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setattr(settings, "tactical_webhook_url", "https://tactical.example.com/hook")

    # Capture the push call
    captured = {}

    def fake_push(change):
        captured["pushed"] = True
        captured["severity"] = change.severity
        return {"recorded": True}

    monkeypatch.setattr(regime_watch, "push_to_tactical", fake_push)

    theses = [_make_thesis("t1", "inflation", "bullish")]
    memo = _FakeMemo("Initial bullish regime")

    result = regime_watch.detect_and_push(theses, memo)
    assert result["changed"] is True
    assert result["pushed"] is True
    assert captured.get("pushed") is True
    assert captured.get("severity") in {"minor", "moderate", "major"}


def test_view_cache_put_get_expiry(monkeypatch):
    from macro_positioning.integration import endpoints

    # Fake MacroPositioningView
    from macro_positioning.integration.contracts import MacroPositioningView

    view = MacroPositioningView(asset="SPY", direction="bullish")
    endpoints._cache_put("SPY|equities", view)
    assert endpoints._cache_get("SPY|equities") is view

    # Invalidate clears
    endpoints.invalidate_view_cache()
    assert endpoints._cache_get("SPY|equities") is None


def test_view_cache_ttl_expires(monkeypatch):
    from macro_positioning.integration import endpoints
    from macro_positioning.integration.contracts import MacroPositioningView

    view = MacroPositioningView(asset="SPY", direction="bullish")
    # Force a past expiry to simulate TTL elapsed
    endpoints._VIEW_CACHE["SPY|equities"] = (0.0, view)
    assert endpoints._cache_get("SPY|equities") is None

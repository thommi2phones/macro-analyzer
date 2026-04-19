"""Tests for macro → tactical READ-direction HTTP client."""
from __future__ import annotations

import httpx
import pytest

from macro_positioning.integration import tactical_client as tc


# ---------------------------------------------------------------------------
# Mock helpers (mirror tests/test_finnhub_connector.py)
# ---------------------------------------------------------------------------

def _install_mock(monkeypatch, routes: dict):
    """Install a fake httpx.Client that routes paths to JSON responses."""
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in routes:
            result = routes[path]
            if isinstance(result, Exception):
                raise result
            status, body = result
            return httpx.Response(status, json=body)
        return httpx.Response(404, json={"error": f"no route {path}"})

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            kwargs.pop("transport", None)
            self._client = real_client(transport=transport, timeout=kwargs.get("timeout", 5.0))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._client.close()

        def get(self, url, **kwargs):
            return self._client.get(url, **kwargs)

    monkeypatch.setattr(tc.httpx, "Client", _FakeClient)


def _set_url(monkeypatch, value):
    monkeypatch.setattr(tc.settings, "tactical_executor_url", value)
    tc.invalidate_cache()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_not_configured_returns_none(monkeypatch):
    _set_url(monkeypatch, "")
    assert tc.fetch_latest_events() is None
    assert tc.fetch_latest_decision() is None
    assert tc.fetch_lifecycle_latest() is None
    assert tc.fetch_health() is None
    assert tc.is_configured() is False


def test_is_configured(monkeypatch):
    _set_url(monkeypatch, "https://tactical.example.com")
    assert tc.is_configured() is True


def test_fetch_latest_events_happy_path_list(monkeypatch):
    _set_url(monkeypatch, "https://tactical.example.com")
    _install_mock(monkeypatch, {
        "/events": (200, [{"event_id": "e1", "payload": {"symbol": "SPY"}}]),
    })
    events = tc.fetch_latest_events(limit=5)
    assert isinstance(events, list)
    assert len(events) == 1
    assert events[0]["event_id"] == "e1"


def test_fetch_latest_events_happy_path_wrapped(monkeypatch):
    """Tactical returns {ok: true, events: [...]} in some responses."""
    _set_url(monkeypatch, "https://tactical.example.com")
    _install_mock(monkeypatch, {
        "/events": (200, {"ok": True, "events": [{"event_id": "e2"}]}),
    })
    events = tc.fetch_latest_events()
    assert events == [{"event_id": "e2"}]


def test_fetch_latest_events_unexpected_shape_returns_none(monkeypatch):
    _set_url(monkeypatch, "https://tactical.example.com")
    _install_mock(monkeypatch, {
        "/events": (200, {"no_events_key": True}),
    })
    assert tc.fetch_latest_events() is None


def test_fetch_latest_events_500_returns_none(monkeypatch):
    _set_url(monkeypatch, "https://tactical.example.com")
    _install_mock(monkeypatch, {
        "/events": (500, {"error": "boom"}),
    })
    assert tc.fetch_latest_events() is None


def test_cache_prevents_second_http_call(monkeypatch):
    _set_url(monkeypatch, "https://tactical.example.com")
    call_count = [0]

    def counting_handler(request: httpx.Request) -> httpx.Response:
        call_count[0] += 1
        return httpx.Response(200, json=[{"event_id": f"e{call_count[0]}"}])

    transport = httpx.MockTransport(counting_handler)
    real_client = httpx.Client

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            kwargs.pop("transport", None)
            self._client = real_client(transport=transport, timeout=5.0)
        def __enter__(self): return self
        def __exit__(self, *exc): self._client.close()
        def get(self, url, **kwargs): return self._client.get(url, **kwargs)

    monkeypatch.setattr(tc.httpx, "Client", _FakeClient)

    tc.invalidate_cache()
    first = tc.fetch_latest_events(limit=5)
    second = tc.fetch_latest_events(limit=5)
    assert first == second
    assert call_count[0] == 1  # cached


def test_fetch_tactical_snapshot_bundles_all(monkeypatch):
    _set_url(monkeypatch, "https://tactical.example.com")
    _install_mock(monkeypatch, {
        "/health": (200, {"ok": True}),
        "/events": (200, [{"event_id": "e1"}]),
        "/decision/latest": (200, {"decision": {"action": "LONG"}, "ok": True}),
        "/lifecycle/latest": (200, {"ok": True, "setups": []}),
    })
    snap = tc.fetch_tactical_snapshot()
    assert snap["configured"] is True
    assert snap["events"] == [{"event_id": "e1"}]
    assert snap["latest_decision"]["decision"]["action"] == "LONG"
    assert snap["lifecycle"]["ok"] is True
    assert snap["health"]["ok"] is True


def test_fetch_tactical_snapshot_when_unreachable_returns_safe_defaults(monkeypatch):
    _set_url(monkeypatch, "https://tactical.example.com")

    def boom(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "down"})

    transport = httpx.MockTransport(boom)
    real_client = httpx.Client

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            kwargs.pop("transport", None)
            self._client = real_client(transport=transport, timeout=5.0)
        def __enter__(self): return self
        def __exit__(self, *exc): self._client.close()
        def get(self, url, **kwargs): return self._client.get(url, **kwargs)

    monkeypatch.setattr(tc.httpx, "Client", _FakeClient)
    tc.invalidate_cache()

    snap = tc.fetch_tactical_snapshot()
    assert snap["configured"] is True
    assert snap["events"] is None
    assert snap["latest_decision"] is None
    assert snap["lifecycle"] is None

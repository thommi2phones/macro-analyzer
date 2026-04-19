"""Tests for brain/transcription.py — N8N audio webhook client."""
from __future__ import annotations

import httpx
import pytest

from macro_positioning.brain import transcription as trans


# ---------------------------------------------------------------------------
# Mocking helpers (mirror the httpx.MockTransport pattern from other tests)
# ---------------------------------------------------------------------------

def _install_fake_client(monkeypatch, handler):
    """Replace httpx.Client inside the transcription module with one that
    uses MockTransport. Returns the installed transport for assertions.
    """
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client  # bind the real class before monkeypatching

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            kwargs.pop("transport", None)
            self._client = real_client(transport=transport, **{k: v for k, v in kwargs.items() if k == "timeout"})

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._client.close()

        def post(self, url, **kwargs):
            return self._client.post(url, **kwargs)

    monkeypatch.setattr(trans.httpx, "Client", _FakeClient)
    return transport


def _set_webhook(monkeypatch, value):
    """Set settings.n8n_audio_webhook_url for a test."""
    monkeypatch.setattr(trans.settings, "n8n_audio_webhook_url", value)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_missing_webhook_raises_unavailable(monkeypatch):
    _set_webhook(monkeypatch, "")
    with pytest.raises(trans.TranscriptionUnavailable):
        trans.transcribe_audio_url("https://example.com/episode.mp3")


def test_happy_path_text_field(monkeypatch):
    _set_webhook(monkeypatch, "https://n8n.example.com/webhook/audio")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert "audio_url" in request.content.decode()
        return httpx.Response(200, json={"text": "This is the transcribed episode."})

    _install_fake_client(monkeypatch, handler)
    result = trans.transcribe_audio_url("https://cdn.example.com/ep.mp3")
    assert isinstance(result, trans.TranscriptionResult)
    assert result.text == "This is the transcribed episode."
    assert result.model == "gemini-2.5-pro"
    assert result.latency_ms >= 0


def test_happy_path_output_field(monkeypatch):
    """N8N sometimes wraps Gemini output under 'output' instead of 'text'."""
    _set_webhook(monkeypatch, "https://n8n.example.com/webhook/audio")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"output": "Alt shape transcript."})

    _install_fake_client(monkeypatch, handler)
    result = trans.transcribe_audio_url("https://cdn.example.com/ep.mp3")
    assert result.text == "Alt shape transcript."


def test_happy_path_first_incoming_item_wrapped(monkeypatch):
    """N8N 'firstIncomingItem' responds with the whole item, possibly wrapped."""
    _set_webhook(monkeypatch, "https://n8n.example.com/webhook/audio")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"json": {"text": "Wrapped transcript text."}}])

    _install_fake_client(monkeypatch, handler)
    result = trans.transcribe_audio_url("https://cdn.example.com/ep.mp3")
    assert result.text == "Wrapped transcript text."


def test_empty_response_raises(monkeypatch):
    _set_webhook(monkeypatch, "https://n8n.example.com/webhook/audio")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"text": ""})

    _install_fake_client(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="empty"):
        trans.transcribe_audio_url("https://cdn.example.com/ep.mp3")


def test_http_500_raises_runtime_error(monkeypatch):
    _set_webhook(monkeypatch, "https://n8n.example.com/webhook/audio")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    _install_fake_client(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="failed"):
        trans.transcribe_audio_url("https://cdn.example.com/ep.mp3")


def test_explicit_webhook_override_wins_over_settings(monkeypatch):
    _set_webhook(monkeypatch, "")  # settings is empty

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"text": "ok"})

    _install_fake_client(monkeypatch, handler)
    override = "https://override.example.com/webhook/audio"
    result = trans.transcribe_audio_url(
        "https://cdn.example.com/ep.mp3",
        webhook_url=override,
    )
    assert result.text == "ok"
    assert captured["url"] == override


def test_is_configured(monkeypatch):
    _set_webhook(monkeypatch, "")
    assert trans.is_configured() is False
    _set_webhook(monkeypatch, "https://x.example.com/webhook/a")
    assert trans.is_configured() is True


def test_extract_text_variants():
    # Direct dict shapes
    assert trans._extract_text_from_response({"text": "a"}) == "a"
    assert trans._extract_text_from_response({"output": "b"}) == "b"
    assert trans._extract_text_from_response({"content": "c"}) == "c"
    assert trans._extract_text_from_response({"transcript": "d"}) == "d"
    # List wrapper
    assert trans._extract_text_from_response([{"text": "e"}]) == "e"
    # N8N json wrapper
    assert trans._extract_text_from_response({"json": {"text": "f"}}) == "f"
    # Raw string
    assert trans._extract_text_from_response("plain") == "plain"
    # Unknown shape falls back to JSON dump (so we at least see it)
    stub = {"weird_shape": 1}
    out = trans._extract_text_from_response(stub)
    assert "weird_shape" in out

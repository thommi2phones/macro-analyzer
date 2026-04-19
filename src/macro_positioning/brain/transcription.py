"""Audio transcription — routed to N8N → Gemini audio/transcribe.

Single-responsibility module. Unlike brain/backends.generate() which is
optimized for text-in/text-out LLM calls, transcription has a different
shape (no system prompt, no temperature, audio input), different failure
modes, and different latency profile (can run 30-180s for a long episode).

Keeping it separate from backends.py keeps the generate() dispatcher tight.

Path: tactical Python → N8N webhook → Gemini audio/transcribe → response
Cost: $0 (uses the user's unlimited Vertex access via N8N)

N8N workflow side (user builds once in the N8N UI):
  Webhook (POST /webhook/macro-brain-audio)
      body: { "audio_url": "https://..." }
      ↓
  Google Gemini (resource: audio, operation: transcribe)
      - Input type: URL
      - Audio URLs: {{ $json.body.audio_url }}
      - Model: gemini-2.5-pro
      ↓
  Respond to Webhook  (First incoming item → returns { text: "..." })
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from macro_positioning.brain.observability import log_brain_call
from macro_positioning.core.settings import settings

logger = logging.getLogger(__name__)


class TranscriptionResult:
    """Container for a successful transcription."""

    def __init__(
        self,
        text: str,
        model: str,
        latency_ms: float,
        audio_seconds: float | None = None,
        raw: Any = None,
    ) -> None:
        self.text = text
        self.model = model
        self.latency_ms = latency_ms
        self.audio_seconds = audio_seconds
        self.raw = raw

    def __repr__(self) -> str:
        return (
            f"TranscriptionResult(chars={len(self.text)}, "
            f"model={self.model!r}, latency={self.latency_ms:.0f}ms, "
            f"audio_sec={self.audio_seconds})"
        )


class TranscriptionUnavailable(RuntimeError):
    """No audio webhook configured, or audio webhook returned an error."""


def _extract_text_from_response(data: Any) -> str:
    """Pull the transcript text out of whatever shape N8N returns.

    N8N / Gemini audio/transcribe commonly returns one of:
      { "text": "..." }
      { "output": "..." }
      { "content": "..." }
      { "json": { ... } }   # when 'firstIncomingItem' wraps the Gemini output
      list of items where the first has one of the above
    """
    if isinstance(data, list) and data:
        data = data[0]
    if isinstance(data, dict):
        # Unwrap N8N 'json' wrapper if present
        if "json" in data and isinstance(data["json"], (dict, list)):
            data = data["json"]
        if isinstance(data, list) and data:
            data = data[0]
    if isinstance(data, dict):
        # Prefer the first text-like key present, even if its value is empty.
        # (An empty-string value from Gemini means "I produced no transcript"
        # — we want that to flow through to the empty-response check upstream,
        # not get masked by a JSON dump of the whole envelope.)
        for key in ("text", "output", "content", "transcript", "transcription"):
            if key in data:
                val = data.get(key)
                if isinstance(val, str):
                    return val
        # No text-like key at all → surface the raw envelope for debugging
        return json.dumps(data)
    if isinstance(data, str):
        return data
    return str(data)


def transcribe_audio_url(
    audio_url: str,
    *,
    timeout: float = 600.0,
    webhook_url: str | None = None,
) -> TranscriptionResult:
    """POST { audio_url } to the N8N audio webhook and return the transcript.

    Args:
        audio_url: Public MP3 URL (from podcast RSS enclosure)
        timeout: HTTP timeout in seconds — transcription can take a minute+
        webhook_url: Override the configured webhook URL (useful for tests)

    Raises:
        TranscriptionUnavailable if no webhook is configured
        RuntimeError (or httpx exceptions) on HTTP failure
    """
    url = webhook_url or settings.n8n_audio_webhook_url
    if not url:
        raise TranscriptionUnavailable(
            "N8N audio webhook not configured. "
            "Set MPA_N8N_AUDIO_WEBHOOK_URL in .env. "
            "See brain/transcription.py docstring for N8N workflow setup."
        )

    payload = {"audio_url": audio_url}
    logger.info("Transcription request → N8N (audio: %s)", audio_url)

    t0 = time.time()
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
        data = response.json()
    except httpx.HTTPError as e:
        latency_ms = (time.time() - t0) * 1000
        log_brain_call(
            call_type="transcription",
            backend="n8n-audio",
            model="",
            input_size=0,
            output_size=0,
            latency_ms=latency_ms,
            success=False,
            error=f"http: {e}",
        )
        raise RuntimeError(f"Audio transcription request failed: {e}") from e

    latency_ms = (time.time() - t0) * 1000
    text = _extract_text_from_response(data).strip()

    if not text:
        log_brain_call(
            call_type="transcription",
            backend="n8n-audio",
            model="",
            input_size=0,
            output_size=0,
            latency_ms=latency_ms,
            success=False,
            error="empty response",
        )
        raise RuntimeError(f"Audio transcription returned empty text. Raw: {str(data)[:200]}")

    log_brain_call(
        call_type="transcription",
        backend="n8n-audio",
        model="gemini-2.5-pro",
        input_size=0,        # we don't know audio size unless we download — skipping
        output_size=len(text),
        latency_ms=latency_ms,
        success=True,
    )

    logger.info("Transcription ok: %d chars in %.0fms", len(text), latency_ms)
    return TranscriptionResult(
        text=text,
        model="gemini-2.5-pro",
        latency_ms=latency_ms,
        raw=data,
    )


def is_configured() -> bool:
    """Return True if audio transcription is ready to use."""
    return bool(settings.n8n_audio_webhook_url)

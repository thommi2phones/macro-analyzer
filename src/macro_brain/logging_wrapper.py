"""Logging contract enforcement — every LLM call must go through this.

Implements the spec in macro-analyzer's `docs/logging_contract.md`.

The wrapper:
1. Generates a `call_id` (UUID) BEFORE the call so failures still log
2. Times the call
3. Captures the rendered prompt + structured inputs
4. Captures raw model output
5. Persists everything to the agent_call_log table (or training_corpus
   JSONL when running locally without DB access)
6. Re-raises errors after logging — never silently swallow

Storage strategy:
- Production: write to agent_call_log over HTTP back to macro-analyzer's
  DB (or shared SQLite if colocated). Endpoint: POST /agent-calls
- Local dev: append JSONL to ./training_corpus/{date}.jsonl

This module is the ONLY way LLM calls should happen in macro-brain.
If you find yourself calling an LLM SDK directly, refactor to use
log_agent_call() — see Application Agent's CLAUDE.md.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field


# Where to write JSONL training_corpus entries when not pushing to a
# central DB. Override via env: MACRO_BRAIN_CORPUS_DIR.
CORPUS_DIR = Path(os.environ.get(
    "MACRO_BRAIN_CORPUS_DIR",
    str(Path(__file__).resolve().parent.parent.parent / "training_corpus"),
))


class AgentCallRecord(BaseModel):
    """Mirrors macro-analyzer's `agent_call_log` table schema."""

    call_id: str
    agent_name: str
    called_at: str  # ISO 8601 UTC
    model_provider: str
    model_name: str
    prompt_version: str
    input_payload_json: str
    output_payload_json: str
    context_json: str | None = None
    latency_ms: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None
    success: int = 0  # 0 or 1
    error_message: str | None = None
    attributed_setup_id: str | None = None
    attributed_trade_id: str | None = None
    attributed_outcome_pnl: float | None = None
    # ML loop phase 2 item 7: pinned at corpus-write time so prompt
    # revisions are visible alongside model churn.
    # Convention: f"{model_name}@{prompt_version}"
    # e.g. "gemini-2.5-pro@regime_classifier@v1"
    model_version: str | None = None
    call_type: str | None = None
    quality_score: float | None = None


def _write_corpus_record(record: AgentCallRecord) -> None:
    """Append a record as one JSON line to today's training corpus file.

    Best-effort — never raise to caller. The point of logging is to
    NEVER lose a call; failure to write should be visible in stderr but
    must not break the LLM call's actual return.
    """
    try:
        CORPUS_DIR.mkdir(parents=True, exist_ok=True)
        date_part = record.called_at[:10]  # YYYY-MM-DD
        path = CORPUS_DIR / f"{date_part}.jsonl"
        with path.open("a") as f:
            f.write(record.model_dump_json() + "\n")
    except Exception as exc:
        import sys
        print(f"[macro-brain] WARNING: failed to write corpus record {record.call_id}: {exc}", file=sys.stderr)


def _estimate_cost(provider: str, model: str, input_tokens: int | None, output_tokens: int | None) -> float | None:
    """Rough USD cost estimate from token counts. Returns None when
    we don't have prices for that model. Update as new models ship.
    """
    if input_tokens is None or output_tokens is None:
        return None
    # Per-million-token prices (input, output) in USD. As of 2026-05.
    prices = {
        ("gemini", "gemini-2.5-pro"): (1.25, 10.00),
        ("gemini", "gemini-2.5-flash"): (0.075, 0.30),
        ("anthropic", "claude-sonnet-4-5"): (3.00, 15.00),
        ("anthropic", "claude-opus-4-7"): (15.00, 75.00),
        ("openai", "gpt-5"): (5.00, 15.00),  # placeholder
    }
    rates = prices.get((provider.lower(), model.lower()))
    if not rates:
        return None
    in_rate, out_rate = rates
    return (input_tokens / 1_000_000.0) * in_rate + (output_tokens / 1_000_000.0) * out_rate


def log_agent_call(
    *,
    agent_name: str,
    model_provider: str,
    model_name: str,
    prompt_version: str,
    input_payload: dict,
    call_fn: Callable[[], dict],
    context: dict | None = None,
) -> dict:
    """Run an LLM call with full logging.

    Usage:
        result = log_agent_call(
            agent_name="regime_classifier",
            model_provider="gemini",
            model_name="gemini-2.5-pro",
            prompt_version="regime_classifier@v1",
            input_payload={"prompt": rendered_prompt, "context": ...},
            call_fn=lambda: gemini.generate(rendered_prompt),
            context={"active_setups": 4, "stale_sources": ["xyz"]},
        )

    Returns the dict that `call_fn()` returned. Always logs — even on
    exception.
    """
    call_id = str(uuid.uuid4())
    started = time.monotonic()
    success = 0
    error_message: str | None = None
    output_payload: dict = {}

    try:
        output_payload = call_fn()
        if not isinstance(output_payload, dict):
            output_payload = {"raw": output_payload}
        success = 1
        return output_payload
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        latency_ms = int((time.monotonic() - started) * 1000)
        usage = output_payload.get("usage", {}) if isinstance(output_payload, dict) else {}
        in_tok = usage.get("input_tokens") or usage.get("prompt_tokens")
        out_tok = usage.get("output_tokens") or usage.get("completion_tokens")

        record = AgentCallRecord(
            call_id=call_id,
            agent_name=agent_name,
            called_at=datetime.now(UTC).isoformat(),
            model_provider=model_provider,
            model_name=model_name,
            prompt_version=prompt_version,
            model_version=f"{model_name}@{prompt_version}",
            input_payload_json=json.dumps(input_payload, default=str),
            output_payload_json=json.dumps(output_payload, default=str),
            context_json=json.dumps(context, default=str) if context else None,
            latency_ms=latency_ms,
            input_tokens=in_tok,
            output_tokens=out_tok,
            estimated_cost_usd=_estimate_cost(model_provider, model_name, in_tok, out_tok),
            success=success,
            error_message=error_message,
        )
        _write_corpus_record(record)

"""Macro synthesis — routed to any configured LLM backend.

Takes all ingested content (newsletters, FRED, notes, chart reads) and
produces structured positioning analysis through a single model call.

Default path: direct API to Gemini 2.5 Pro. Escalation: Claude Sonnet.
Fallback: Ollama local. N8N is optional, not the default.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime

from macro_positioning.brain.backends import generate
from macro_positioning.brain.observability import log_brain_call
from macro_positioning.brain.prompts import MACRO_ANALYSIS_PROMPT, MACRO_SYSTEM_PROMPT
from macro_positioning.core.models import (
    Evidence,
    MarketObservation,
    NormalizedDocument,
    Thesis,
    ThesisStatus,
    ViewDirection,
)
from macro_positioning.core.settings import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Input formatting (unchanged — same across all backends)
# ---------------------------------------------------------------------------

def _format_documents(documents: list[NormalizedDocument]) -> str:
    if not documents:
        return "(No newsletter content available for this run)"

    blocks = []
    for doc in documents:
        text = doc.cleaned_text or doc.raw_text
        if len(text) > 20000:
            text = text[:20000] + "\n... [truncated]"
        blocks.append(
            f"### {doc.title}\n"
            f"Source: {doc.source_id} | Date: {doc.published_at.strftime('%Y-%m-%d')}\n"
            f"{text}"
        )
    return "\n\n---\n\n".join(blocks)


def _format_fred_data(observations: list[MarketObservation]) -> str:
    fred_obs = [o for o in observations if o.source and "fred" in o.source.lower()]
    if not fred_obs:
        return "(No FRED data available)"
    lines = []
    for o in fred_obs:
        interp = f" — {o.interpretation}" if o.interpretation else ""
        lines.append(
            f"- {o.market}/{o.metric}: {o.value} "
            f"(as of {o.as_of.strftime('%Y-%m-%d')}){interp}"
        )
    return "\n".join(lines)


def _format_market_obs(observations: list[MarketObservation]) -> str:
    non_fred = [o for o in observations if not (o.source and "fred" in o.source.lower())]
    if not non_fred:
        return "(No additional market observations)"
    return "\n".join(f"- {o.market}/{o.metric}: {o.value}" for o in non_fred)


def _format_notes(notes: list[str]) -> str:
    if not notes:
        return "(No analyst notes provided)"
    return "\n".join(f"- {n}" for n in notes)


def _format_chart_reads(chart_reads: list[dict]) -> str:
    if not chart_reads:
        return "(No chart reads available)"
    blocks = []
    for i, read in enumerate(chart_reads, 1):
        blocks.append(
            f"Chart {i}: {read.get('asset', 'unknown')} "
            f"{read.get('timeframe', '')}\n"
            f"  Trend: {read.get('trend_direction', '')}\n"
            f"  Read: {read.get('summary', '')}"
        )
    return "\n".join(blocks)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def _parse_theses(data: dict, documents: list[NormalizedDocument]) -> list[Thesis]:
    theses = []
    source_ids = list({d.source_id for d in documents})

    for t in data.get("theses", []):
        try:
            direction = ViewDirection(t.get("direction", "neutral"))
        except ValueError:
            direction = ViewDirection.neutral

        thesis_text = t.get("thesis", "").strip()
        if not thesis_text:
            continue

        thesis_id = hashlib.sha1(
            f"brain|{thesis_text}|{datetime.now(UTC).isoformat()}".encode()
        ).hexdigest()[:16]

        evidence = [
            Evidence(
                document_id=doc.document_id,
                source_id=doc.source_id,
                excerpt=f"Synthesized from: {doc.title}",
                published_at=doc.published_at,
                url=doc.url,
            )
            for doc in documents[:3]
        ]

        theses.append(Thesis(
            thesis_id=thesis_id,
            thesis=thesis_text,
            theme=t.get("theme", "macro"),
            horizon=t.get("horizon", settings.default_horizon),
            direction=direction,
            assets=t.get("assets", []),
            catalysts=t.get("catalysts", []),
            risks=t.get("risks", []),
            implied_positioning=t.get("implied_positioning", []),
            confidence=min(max(float(t.get("confidence", 0.5)), 0.0), 1.0),
            freshness_score=0.9,
            status=ThesisStatus.active,
            source_ids=source_ids,
            evidence=evidence,
        ))

    return theses


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def run_synthesis(
    documents: list[NormalizedDocument],
    observations: list[MarketObservation] | None = None,
    analyst_notes: list[str] | None = None,
    chart_reads: list[dict] | None = None,
    backend: str = "gemini",
):
    """Run one macro synthesis pass on the configured backend."""
    from macro_positioning.brain.client import SynthesisResult

    observations = observations or []
    analyst_notes = analyst_notes or []
    chart_reads = chart_reads or []

    user_prompt = MACRO_ANALYSIS_PROMPT.format(
        documents_block=_format_documents(documents),
        fred_block=_format_fred_data(observations),
        market_block=_format_market_obs(observations),
        notes_block=_format_notes(analyst_notes),
        chart_block=_format_chart_reads(chart_reads),
    )

    logger.info(
        "Brain synthesis [%s]: %d docs, %d obs, %d notes, %d charts",
        backend, len(documents), len(observations), len(analyst_notes), len(chart_reads),
    )

    try:
        result = generate(
            backend=backend,
            system_prompt=MACRO_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.3,
            max_tokens=16384,
            json_mode=True,
        )
    except Exception as e:
        logger.error("Brain synthesis failed on backend %s: %s", backend, e)
        log_brain_call(
            call_type="synthesis",
            backend=backend,
            model="",
            input_size=len(user_prompt),
            output_size=0,
            latency_ms=0.0,
            success=False,
            error=str(e),
        )
        return SynthesisResult(theses=[], model_used=backend)

    try:
        data = json.loads(_strip_fences(result.text))
    except json.JSONDecodeError as e:
        logger.error("Brain returned non-JSON: %s", e)
        logger.debug("Raw response first 2000 chars: %s", result.text[:2000])
        log_brain_call(
            call_type="synthesis",
            backend=backend,
            model=result.model,
            input_size=len(user_prompt),
            output_size=len(result.text),
            latency_ms=result.latency_ms,
            success=False,
            error=f"JSON parse: {e}",
        )
        return SynthesisResult(theses=[], model_used=result.model, latency_ms=result.latency_ms)

    theses = _parse_theses(data, documents)
    logger.info("Brain produced %d theses via %s", len(theses), result.model)

    log_brain_call(
        call_type="synthesis",
        backend=backend,
        model=result.model,
        input_size=len(user_prompt),
        output_size=len(result.text),
        latency_ms=result.latency_ms,
        success=True,
        theses_count=len(theses),
    )

    return SynthesisResult(
        theses=theses,
        market_regime=data.get("market_regime", ""),
        top_trades=data.get("top_trades", []),
        key_risks=data.get("key_risks", []),
        data_gaps=data.get("data_gaps", []),
        model_used=result.model,
        latency_ms=result.latency_ms,
    )

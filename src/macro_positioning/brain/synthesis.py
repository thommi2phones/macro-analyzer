"""Macro synthesis — Gemini 2.5 Pro via N8N.

Takes all ingested content (newsletters, FRED data, analyst notes, chart reads)
and produces structured macro positioning analysis through a single LLM call.

N8N workflow setup (3 nodes):
  1. Webhook — POST, path: "macro-analyzer-gemini", response mode: "Respond to Webhook"
  2. Google Gemini — text/message operation
     - Model: gemini-2.5-pro (performance tier)
     - Content: {{ $json.body.prompt }}
     - Options → System message: {{ $json.body.system_prompt }}
     - JSON output: ON
     - Temperature: 0.3
     - Max output tokens: 16384
  3. Respond to Webhook — first incoming item
"""

from __future__ import annotations

import json
import hashlib
import logging
from datetime import UTC, datetime

import httpx

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
# Input formatting
# ---------------------------------------------------------------------------

def _format_documents(documents: list[NormalizedDocument]) -> str:
    if not documents:
        return "(No newsletter content available for this run)"

    blocks = []
    for doc in documents:
        text = doc.cleaned_text or doc.raw_text
        # Gemini Pro has 1M context — allow 20k per doc
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
        asset = read.get("asset", "unknown")
        tf = read.get("timeframe", "")
        trend = read.get("trend_direction", "")
        summary = read.get("summary", "")
        blocks.append(
            f"Chart {i}: {asset} {tf}\n"
            f"  Trend: {trend}\n"
            f"  Read: {summary}"
        )
    return "\n".join(blocks)


# ---------------------------------------------------------------------------
# N8N webhook call
# ---------------------------------------------------------------------------

def _call_brain(system_prompt: str, prompt: str, timeout: float = 180.0) -> str:
    """Send the synthesis request to N8N → Gemini and return raw response text."""
    webhook_url = settings.n8n_webhook_url
    if not webhook_url:
        raise RuntimeError(
            "N8N webhook URL not configured. Set MPA_N8N_WEBHOOK_URL in .env."
        )

    payload = {
        "system_prompt": system_prompt,
        "prompt": prompt,
    }

    logger.info("Brain synthesis request → N8N (prompt: %d chars)", len(prompt))

    with httpx.Client(timeout=timeout) as client:
        response = client.post(webhook_url, json=payload)
        response.raise_for_status()

    data = response.json()

    if isinstance(data, dict):
        text = data.get("text") or data.get("output") or data.get("content", "")
        if not text:
            text = json.dumps(data)
        return text
    elif isinstance(data, str):
        return data
    return json.dumps(data)


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

        thesis = Thesis(
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
        )
        theses.append(thesis)

    return theses


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def run_synthesis(
    documents: list[NormalizedDocument],
    observations: list[MarketObservation] | None = None,
    analyst_notes: list[str] | None = None,
    chart_reads: list[dict] | None = None,
):
    """Run one macro synthesis pass. Returns a SynthesisResult."""
    from macro_positioning.brain.client import SynthesisResult

    observations = observations or []
    analyst_notes = analyst_notes or []
    chart_reads = chart_reads or []

    prompt = MACRO_ANALYSIS_PROMPT.format(
        documents_block=_format_documents(documents),
        fred_block=_format_fred_data(observations),
        market_block=_format_market_obs(observations),
        notes_block=_format_notes(analyst_notes),
        chart_block=_format_chart_reads(chart_reads),
    )

    logger.info(
        "Brain synthesis: %d docs, %d obs, %d notes, %d charts",
        len(documents), len(observations), len(analyst_notes), len(chart_reads),
    )

    raw_text = _call_brain(
        system_prompt=MACRO_SYSTEM_PROMPT,
        prompt=prompt,
    )

    try:
        data = json.loads(_strip_fences(raw_text))
    except json.JSONDecodeError as e:
        logger.error("Brain returned non-JSON response: %s", e)
        logger.debug("Raw response (first 2000 chars): %s", raw_text[:2000])
        return SynthesisResult(theses=[])

    theses = _parse_theses(data, documents)

    logger.info("Brain produced %d theses", len(theses))

    return SynthesisResult(
        theses=theses,
        market_regime=data.get("market_regime", ""),
        top_trades=data.get("top_trades", []),
        key_risks=data.get("key_risks", []),
        data_gaps=data.get("data_gaps", []),
    )

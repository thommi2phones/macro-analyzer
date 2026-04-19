"""Gemini-powered macro synthesis engine (via N8N webhook proxy).

Takes all ingested content (newsletter text, FRED observations, market data,
analyst notes) and produces structured macro positioning analysis.

The LLM call is routed through an N8N webhook workflow that proxies to
Google Vertex AI / Gemini using the unlimited API key available there.

N8N workflow setup (3 nodes, takes 60 seconds):
  1. Webhook node — POST, path: "macro-analyzer-gemini", response mode: "Respond to Webhook"
  2. Google Gemini node — resource: text, operation: message
     - Model: gemini-2.5-flash
     - Content: {{ $json.body.prompt }}
     - System message (in Options): {{ $json.body.system_prompt }}
     - JSON output: ON
     - Temperature: 0.3
     - Max output tokens: 8192
  3. Respond to Webhook node — respond with: first incoming item

Set MPA_N8N_WEBHOOK_URL in .env to the webhook URL from step 1.
"""

from __future__ import annotations

import json
import hashlib
import logging
from datetime import UTC, datetime

import httpx

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
# System prompt — the macro analyst persona
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a senior macro strategist at a multi-strategy fund. Your job is to
read all available market intelligence — newsletters, economic data, market
observations, analyst notes — and produce a clear, actionable macro
positioning analysis.

You think in terms of:
- Directional bias (bullish / bearish / neutral / mixed / watchful)
- Time horizons (tactical 2-8 weeks, medium 1-3 months, structural 6-18 months)
- Asset class implications (rates, equities, commodities, gold, FX, crypto, credit, energy)
- Conviction levels (0.0 to 1.0 scale)
- Cross-asset confirmation or divergence
- Key risks and catalysts that could shift the view

You are direct, concise, and opinionated. You take positions. You don't hedge
everything with "it depends." When the data is mixed, you say so and explain
what would tip the balance.

IMPORTANT: You synthesize across ALL inputs to form a coherent view.
Individual newsletters may contradict each other — your job is to weigh them,
find consensus where it exists, flag divergences, and form your own view.
"""


# ---------------------------------------------------------------------------
# Analysis prompt template
# ---------------------------------------------------------------------------

ANALYSIS_PROMPT = """\
Analyze the following macro intelligence package and produce structured
positioning output.

## Newsletter / Commentary Content
{documents_block}

## Live Economic Data (FRED)
{fred_block}

## Additional Market Observations
{market_block}

## Analyst Notes
{notes_block}

---

Based on ALL of the above, produce your analysis as a JSON object with this
exact structure:

```json
{{
  "theses": [
    {{
      "thesis": "Clear, specific statement of the macro view",
      "theme": "One of: inflation, growth, labor, housing, policy, liquidity, fiscal, geopolitics, commodities, equities, rates, energy, crypto, fx, credit",
      "direction": "One of: bullish, bearish, neutral, mixed, watchful",
      "horizon": "e.g. 2-8 weeks, 1-3 months, 6-18 months",
      "assets": ["List of affected asset classes"],
      "catalysts": ["What would accelerate this thesis"],
      "risks": ["What could invalidate this thesis"],
      "implied_positioning": ["Specific trade expressions or positioning suggestions"],
      "confidence": 0.75
    }}
  ],
  "market_regime": "Brief description of the current macro regime",
  "top_trades": [
    "Ranked list of highest-conviction trade expressions"
  ],
  "key_risks": [
    "Top 3-5 risks across all theses"
  ],
  "data_gaps": [
    "What additional data would sharpen the analysis"
  ]
}}
```

Rules:
- Extract 5-15 theses depending on how much content is available
- Each thesis should be a specific, falsifiable claim — not vague commentary
- Confidence should reflect how much evidence supports the view
- If multiple sources agree, confidence goes up
- If sources contradict, note the divergence and pick a side with lower confidence
- implied_positioning should be actionable: "Long gold via GLD", "Short duration", "Overweight energy equities"
- Don't just repeat what the newsletters said — synthesize and add your own analysis
- If FRED data contradicts newsletter narrative, flag it explicitly

Respond ONLY with the JSON object, no markdown fences, no commentary.
"""


# ---------------------------------------------------------------------------
# Input formatting
# ---------------------------------------------------------------------------

def _format_documents(documents: list[NormalizedDocument]) -> str:
    if not documents:
        return "(No newsletter content available for this run)"

    blocks = []
    for doc in documents:
        text = doc.cleaned_text or doc.raw_text
        if len(text) > 8000:
            text = text[:8000] + "\n... [truncated]"
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
        lines.append(f"- {o.market}/{o.metric}: {o.value} (as of {o.as_of.strftime('%Y-%m-%d')}){interp}")
    return "\n".join(lines)


def _format_market_obs(observations: list[MarketObservation]) -> str:
    non_fred = [o for o in observations if not (o.source and "fred" in o.source.lower())]
    if not non_fred:
        return "(No additional market observations)"

    lines = []
    for o in non_fred:
        lines.append(f"- {o.market}/{o.metric}: {o.value}")
    return "\n".join(lines)


def _format_notes(notes: list[str]) -> str:
    if not notes:
        return "(No analyst notes provided)"
    return "\n".join(f"- {n}" for n in notes)


# ---------------------------------------------------------------------------
# N8N webhook call
# ---------------------------------------------------------------------------

def _call_n8n_webhook(system_prompt: str, prompt: str, timeout: float = 120.0) -> str:
    """Send the analysis request to N8N webhook → Gemini and return the response text."""
    webhook_url = settings.n8n_webhook_url
    if not webhook_url:
        raise RuntimeError(
            "N8N webhook URL not configured. Set MPA_N8N_WEBHOOK_URL in .env. "
            "See gemini_analyzer.py docstring for N8N workflow setup instructions."
        )

    payload = {
        "system_prompt": system_prompt,
        "prompt": prompt,
    }

    logger.info("Calling N8N Gemini proxy at %s (payload: %d chars)",
                webhook_url, len(prompt))

    with httpx.Client(timeout=timeout) as client:
        response = client.post(webhook_url, json=payload)
        response.raise_for_status()

    data = response.json()

    # N8N Respond to Webhook with "firstIncomingItem" returns the Gemini node output
    # The Gemini node with simplify=true returns { text: "...", ... }
    if isinstance(data, dict):
        # Try common response shapes
        text = data.get("text") or data.get("output") or data.get("content", "")
        if not text and "choices" in data:
            text = data["choices"][0].get("text", "")
        if not text:
            # Fallback: stringify the whole response
            text = json.dumps(data)
        return text
    elif isinstance(data, str):
        return data
    else:
        return json.dumps(data)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def _parse_response(raw_text: str, documents: list[NormalizedDocument]) -> list[Thesis]:
    """Parse Gemini JSON response into Thesis objects."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse Gemini response as JSON: %s", e)
        logger.debug("Raw response (first 2000 chars): %s", raw_text[:2000])
        return []

    theses = []
    raw_theses = data.get("theses", [])
    source_ids = list({d.source_id for d in documents})

    for i, t in enumerate(raw_theses):
        try:
            direction = ViewDirection(t.get("direction", "neutral"))
        except ValueError:
            direction = ViewDirection.neutral

        thesis_text = t.get("thesis", "").strip()
        if not thesis_text:
            continue

        thesis_id = hashlib.sha1(
            f"gemini|{thesis_text}|{datetime.now(UTC).isoformat()}".encode()
        ).hexdigest()[:16]

        evidence = []
        for doc in documents[:3]:
            evidence.append(Evidence(
                document_id=doc.document_id,
                source_id=doc.source_id,
                excerpt=f"Synthesized from: {doc.title}",
                published_at=doc.published_at,
                url=doc.url,
            ))

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

    # Store metadata
    _last_analysis["market_regime"] = data.get("market_regime", "")
    _last_analysis["top_trades"] = data.get("top_trades", [])
    _last_analysis["key_risks"] = data.get("key_risks", [])
    _last_analysis["data_gaps"] = data.get("data_gaps", [])

    logger.info("Parsed %d theses from Gemini response", len(theses))
    return theses


_last_analysis: dict = {
    "market_regime": "",
    "top_trades": [],
    "key_risks": [],
    "data_gaps": [],
}


def get_last_analysis_metadata() -> dict:
    """Return metadata from the last Gemini analysis."""
    return dict(_last_analysis)


# ---------------------------------------------------------------------------
# Main synthesis function
# ---------------------------------------------------------------------------

def analyze_macro(
    documents: list[NormalizedDocument],
    observations: list[MarketObservation] | None = None,
    analyst_notes: list[str] | None = None,
) -> list[Thesis]:
    """Run Gemini macro synthesis over all available inputs via N8N webhook.

    Args:
        documents: All ingested and normalized newsletter/commentary documents
        observations: Market observations (FRED data, prices, etc.)
        analyst_notes: Manual notes or context from the user

    Returns:
        List of synthesized Thesis objects ready for validation and memo generation
    """
    observations = observations or []
    analyst_notes = analyst_notes or []

    prompt = ANALYSIS_PROMPT.format(
        documents_block=_format_documents(documents),
        fred_block=_format_fred_data(observations),
        market_block=_format_market_obs(observations),
        notes_block=_format_notes(analyst_notes),
    )

    logger.info("Sending macro synthesis request via N8N → Gemini with %d docs, %d observations",
                len(documents), len(observations))

    raw_text = _call_n8n_webhook(
        system_prompt=SYSTEM_PROMPT,
        prompt=prompt,
    )

    logger.debug("Gemini response length: %d chars", len(raw_text))
    return _parse_response(raw_text, documents)


# ---------------------------------------------------------------------------
# ThesisExtractor interface adapter
# ---------------------------------------------------------------------------

class GeminiThesisExtractor:
    """Adapter that accumulates all documents and runs a single Gemini synthesis pass."""

    def __init__(self) -> None:
        self._documents: list[NormalizedDocument] = []
        self._observations: list[MarketObservation] = []
        self._notes: list[str] = []

    def set_context(
        self,
        observations: list[MarketObservation] | None = None,
        notes: list[str] | None = None,
    ) -> None:
        self._observations = observations or []
        self._notes = notes or []

    def add_document(self, doc: NormalizedDocument) -> None:
        self._documents.append(doc)

    def synthesize(self) -> list[Thesis]:
        if not self._documents:
            logger.warning("No documents accumulated for Gemini synthesis")
            return []

        return analyze_macro(
            documents=self._documents,
            observations=self._observations,
            analyst_notes=self._notes,
        )

    def reset(self) -> None:
        self._documents.clear()
        self._observations.clear()
        self._notes.clear()

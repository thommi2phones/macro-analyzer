"""BrainClient — unified interface the rest of the app uses for LLM reasoning.

Multi-model, direct-API architecture:
  - Primary: Gemini 2.5 Pro (best macro reasoning, 1M context)
  - Escalation: Claude Sonnet (structured output, careful reasoning)
  - Vision: Gemini 2.5 Pro (native multimodal)
  - Fallback: Ollama local (dev/testing)

Direct API calls — no N8N dependency. N8N is kept as an OPTIONAL advanced
workflow path for users who want it, but not the default.

When Phase 2 splits the Brain into its own repo/service, this interface
stays; only the factory changes from "local Python calls" to "HTTP calls
to macro-brain service".
"""

from __future__ import annotations

import logging
from typing import Protocol

from macro_positioning.core.models import (
    MarketObservation,
    NormalizedDocument,
    Thesis,
)
from macro_positioning.core.settings import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------

class SynthesisResult:
    """Structured output of a macro synthesis call."""

    def __init__(
        self,
        theses: list[Thesis],
        market_regime: str = "",
        top_trades: list[str] | None = None,
        key_risks: list[str] | None = None,
        data_gaps: list[str] | None = None,
        model_used: str = "",
        latency_ms: float = 0.0,
    ) -> None:
        self.theses = theses
        self.market_regime = market_regime
        self.top_trades = top_trades or []
        self.key_risks = key_risks or []
        self.data_gaps = data_gaps or []
        self.model_used = model_used
        self.latency_ms = latency_ms

    def __repr__(self) -> str:
        return (
            f"SynthesisResult(theses={len(self.theses)}, "
            f"regime={self.market_regime[:40]!r}, "
            f"trades={len(self.top_trades)}, "
            f"model={self.model_used!r}, "
            f"latency={self.latency_ms:.0f}ms)"
        )


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

class BrainClient(Protocol):
    def synthesize_macro(
        self,
        documents: list[NormalizedDocument],
        observations: list[MarketObservation] | None = None,
        analyst_notes: list[str] | None = None,
        chart_reads: list[dict] | None = None,
        escalate: bool = False,
    ) -> SynthesisResult: ...

    def analyze_chart(
        self,
        image_url: str,
        asset_context: str = "",
        additional_context: str = "",
    ) -> dict: ...

    def analyze_chart_file(
        self,
        file_path: str,
        asset_context: str = "",
        additional_context: str = "",
    ) -> dict: ...

    @property
    def available(self) -> bool: ...


# ---------------------------------------------------------------------------
# Direct API client
# ---------------------------------------------------------------------------

class DirectAPIBrainClient:
    """Brain that calls Gemini/Claude APIs directly — no N8N, no proxy.

    Routes by task:
      - macro synthesis → primary backend (Gemini 2.5 Pro default)
      - vision → vision backend (Gemini 2.5 Pro default, multimodal)
      - escalation → alternative backend (Claude default, when escalate=True)
    """

    def synthesize_macro(
        self,
        documents,
        observations=None,
        analyst_notes=None,
        chart_reads=None,
        escalate=False,
    ) -> SynthesisResult:
        from macro_positioning.brain.synthesis import run_synthesis

        backend = (
            settings.brain_escalation_backend
            if escalate
            else settings.brain_primary_backend
        )
        return run_synthesis(
            documents=documents,
            observations=observations or [],
            analyst_notes=analyst_notes or [],
            chart_reads=chart_reads or [],
            backend=backend,
        )

    def analyze_chart(
        self,
        image_url: str,
        asset_context: str = "",
        additional_context: str = "",
    ) -> dict:
        from macro_positioning.brain.vision import analyze_chart_url
        return analyze_chart_url(
            image_url=image_url,
            asset_context=asset_context,
            additional_context=additional_context,
            backend=settings.brain_vision_backend,
        )

    def analyze_chart_file(
        self,
        file_path: str,
        asset_context: str = "",
        additional_context: str = "",
    ) -> dict:
        from macro_positioning.brain.vision import analyze_chart_file
        return analyze_chart_file(
            file_path=file_path,
            asset_context=asset_context,
            additional_context=additional_context,
            backend=settings.brain_vision_backend,
        )

    @property
    def available(self) -> bool:
        return bool(
            settings.gemini_api_key
            or settings.anthropic_api_key
            or settings.ollama_base_url
        )


# ---------------------------------------------------------------------------
# Heuristic fallback (no LLM at all)
# ---------------------------------------------------------------------------

class HeuristicBrainClient:
    """Deterministic keyword extractor — always works, no external deps."""

    def synthesize_macro(
        self, documents, observations=None, analyst_notes=None,
        chart_reads=None, escalate=False,
    ) -> SynthesisResult:
        from macro_positioning.brain.heuristic import HeuristicThesisExtractor
        extractor = HeuristicThesisExtractor()
        theses = []
        for doc in documents:
            theses.extend(extractor.extract(
                document_id=doc.document_id,
                source_id=doc.source_id,
                text=doc.cleaned_text,
                published_at=doc.published_at,
                url=doc.url,
            ))
        return SynthesisResult(theses=theses, model_used="heuristic")

    def analyze_chart(self, image_url, asset_context="", additional_context=""):
        return {
            "error": "Vision not available — configure an LLM backend",
            "summary": "Set MPA_GEMINI_API_KEY or MPA_ANTHROPIC_API_KEY",
        }

    def analyze_chart_file(self, file_path, asset_context="", additional_context=""):
        return self.analyze_chart("", asset_context, additional_context)

    @property
    def available(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_brain_client() -> BrainClient:
    """Return the best available Brain client based on configuration.

    Auto-detection (any one of these triggers direct-API mode):
      1. Gemini API key configured
      2. Anthropic API key configured
      3. Ollama reachable at configured URL (tested)
      4. N8N webhook URL configured
    Otherwise falls back to HeuristicBrainClient.
    """
    has_gemini = bool(settings.gemini_api_key)
    has_anthropic = bool(settings.anthropic_api_key)
    has_n8n = bool(settings.n8n_webhook_url)
    has_ollama = _ollama_reachable()

    if has_gemini or has_anthropic or has_n8n or has_ollama:
        backends_available = [
            name for name, avail in [
                ("gemini", has_gemini),
                ("anthropic", has_anthropic),
                ("ollama", has_ollama),
                ("n8n", has_n8n),
            ] if avail
        ]
        logger.info(
            "Brain: direct API mode — available=%s, primary=%s, vision=%s, escalation=%s",
            backends_available,
            settings.brain_primary_backend,
            settings.brain_vision_backend,
            settings.brain_escalation_backend,
        )
        return DirectAPIBrainClient()

    logger.info("Brain: heuristic fallback (no LLM backends configured)")
    return HeuristicBrainClient()


def _ollama_reachable(timeout: float = 0.5) -> bool:
    """Return True if Ollama is responding at the configured URL."""
    import httpx
    try:
        with httpx.Client(timeout=timeout) as c:
            r = c.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
            return r.status_code == 200
    except Exception:
        return False

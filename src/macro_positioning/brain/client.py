"""BrainClient — the single interface the rest of the app uses to talk to the Brain.

Today: wraps local Python functions that call Gemini via N8N webhook.
Phase 2: will wrap HTTP calls to the extracted macro-brain service.

The consumer code (pipeline, API, dashboard) must NEVER import synthesis.py
or vision.py directly. They only touch BrainClient. That's what makes the
Phase 2 extraction mechanical instead of a rewrite.
"""

from __future__ import annotations

import logging
from typing import Protocol

from macro_positioning.core.models import (
    MarketObservation,
    NormalizedDocument,
    Thesis,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------

class SynthesisResult:
    """What the Brain returns from a macro synthesis call."""

    def __init__(
        self,
        theses: list[Thesis],
        market_regime: str = "",
        top_trades: list[str] | None = None,
        key_risks: list[str] | None = None,
        data_gaps: list[str] | None = None,
    ) -> None:
        self.theses = theses
        self.market_regime = market_regime
        self.top_trades = top_trades or []
        self.key_risks = key_risks or []
        self.data_gaps = data_gaps or []

    def __repr__(self) -> str:
        return (
            f"SynthesisResult(theses={len(self.theses)}, "
            f"regime={self.market_regime!r}, "
            f"trades={len(self.top_trades)})"
        )


# ---------------------------------------------------------------------------
# BrainClient interface
# ---------------------------------------------------------------------------

class BrainClient(Protocol):
    """Interface every Brain implementation must satisfy."""

    def synthesize_macro(
        self,
        documents: list[NormalizedDocument],
        observations: list[MarketObservation] | None = None,
        analyst_notes: list[str] | None = None,
        chart_reads: list[dict] | None = None,
    ) -> SynthesisResult:
        """Read all inputs and produce structured macro positioning."""
        ...

    def analyze_chart(
        self,
        image_url: str,
        asset_context: str = "",
        additional_context: str = "",
    ) -> dict:
        """Analyze a single chart from a URL. Returns structured read."""
        ...

    def analyze_chart_file(
        self,
        file_path: str,
        asset_context: str = "",
        additional_context: str = "",
    ) -> dict:
        """Analyze a chart from a local file path."""
        ...

    @property
    def available(self) -> bool:
        """Whether the Brain is configured and ready to call."""
        ...


# ---------------------------------------------------------------------------
# Concrete implementations
# ---------------------------------------------------------------------------

class GeminiBrainClient:
    """Brain backed by Gemini 2.5 Pro via N8N webhook.

    Currently calls local Python functions that POST to N8N. In Phase 2, this
    whole class gets replaced with an HTTP client to the extracted Brain
    service — no changes to consumers.
    """

    def synthesize_macro(
        self,
        documents,
        observations=None,
        analyst_notes=None,
        chart_reads=None,
    ) -> SynthesisResult:
        from macro_positioning.brain.synthesis import run_synthesis
        return run_synthesis(
            documents=documents,
            observations=observations or [],
            analyst_notes=analyst_notes or [],
            chart_reads=chart_reads or [],
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
        )

    @property
    def available(self) -> bool:
        from macro_positioning.core.settings import settings
        return bool(settings.n8n_webhook_url)


class HeuristicBrainClient:
    """Fallback Brain that uses deterministic keyword heuristics.

    Used when no LLM is configured. Keeps the system functional for
    development and as a safety net.
    """

    def synthesize_macro(
        self,
        documents,
        observations=None,
        analyst_notes=None,
        chart_reads=None,
    ) -> SynthesisResult:
        from macro_positioning.brain.heuristic import HeuristicThesisExtractor

        extractor = HeuristicThesisExtractor()
        theses = []
        for doc in documents:
            theses.extend(
                extractor.extract(
                    document_id=doc.document_id,
                    source_id=doc.source_id,
                    text=doc.cleaned_text,
                    published_at=doc.published_at,
                    url=doc.url,
                )
            )
        return SynthesisResult(theses=theses)

    def analyze_chart(self, image_url, asset_context="", additional_context=""):
        return {
            "error": "Chart analysis not available without LLM backend",
            "summary": "Configure N8N webhook to enable vision analysis",
        }

    def analyze_chart_file(self, file_path, asset_context="", additional_context=""):
        return self.analyze_chart("", asset_context, additional_context)

    @property
    def available(self) -> bool:
        return True  # Always available as fallback


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_brain_client() -> BrainClient:
    """Return the best available Brain client based on configuration.

    Auto-detection order:
      1. GeminiBrainClient if N8N webhook is configured
      2. HeuristicBrainClient as fallback
    """
    from macro_positioning.core.settings import settings

    if settings.n8n_webhook_url:
        logger.info("Brain: Gemini (via N8N) — performance tier")
        return GeminiBrainClient()

    logger.info("Brain: heuristic fallback — no LLM credentials configured")
    return HeuristicBrainClient()

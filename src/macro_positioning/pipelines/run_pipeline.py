from __future__ import annotations

import logging
from pathlib import Path

from macro_positioning.brain import BrainClient, build_brain_client
from macro_positioning.core.models import PipelineContext, PipelineRunResult, RawDocument
from macro_positioning.core.settings import settings
from macro_positioning.db.repository import SQLiteRepository
from macro_positioning.db.schema import initialize_database
from macro_positioning.ingestion.base import normalize_document
from macro_positioning.ingestion.sample_sources import sample_context, sample_documents
from macro_positioning.ingestion.source_registry import load_source_registry, source_trust_weights
from macro_positioning.market.fred_provider import FREDMarketDataProvider
from macro_positioning.market.providers import MarketDataProvider, StaticMarketDataProvider
from macro_positioning.market.validation import build_recommendations, validate_theses
from macro_positioning.reports.memo import build_positioning_memo
from macro_positioning.reports.renderers import render_memo_markdown, write_memo_markdown

logger = logging.getLogger(__name__)


class PositioningPipeline:
    """Orchestrates: ingest → Brain synthesis → validate → memo.

    The Brain is injected via BrainClient so the pipeline doesn't care
    whether synthesis happens locally, via Gemini/N8N, or (Phase 2) via a
    remote Brain service.
    """

    def __init__(
        self,
        repository: SQLiteRepository,
        brain: BrainClient,
        source_weights: dict[str, float] | None = None,
    ) -> None:
        self.repository = repository
        self.brain = brain
        self.source_weights = source_weights or {}

    def run(
        self,
        documents: list[RawDocument],
        context: PipelineContext | None = None,
    ) -> PipelineRunResult:
        context = context or PipelineContext()
        normalized = [normalize_document(d) for d in documents]
        for doc in normalized:
            self.repository.save_document(doc)

        # Market observations (FRED live if available, else static)
        provider = _build_market_provider(context)
        observations = provider.gather([])
        if not observations and context.market_observations:
            logger.warning(
                "Live market provider returned 0 observations - using %d static obs",
                len(context.market_observations),
            )
            observations = list(context.market_observations)

        # Brain synthesis (single entry point — handles Gemini or heuristic fallback)
        try:
            result = self.brain.synthesize_macro(
                documents=normalized,
                observations=observations,
                analyst_notes=context.analyst_notes,
            )
            theses = result.theses
            logger.info("Brain produced %d theses", len(theses))
        except Exception as e:
            logger.error("Brain synthesis failed, falling back to heuristic: %s", e, exc_info=True)
            from macro_positioning.brain import HeuristicThesisExtractor
            extractor = HeuristicThesisExtractor()
            theses = []
            for doc in normalized:
                theses.extend(extractor.extract(
                    document_id=doc.document_id,
                    source_id=doc.source_id,
                    text=doc.cleaned_text,
                    published_at=doc.published_at,
                    url=doc.url,
                ))

        for thesis in theses:
            self.repository.save_thesis(thesis)

        validated = validate_theses(theses, observations)
        recommendations = build_recommendations(validated)

        memo = build_positioning_memo(
            theses,
            validated_theses=validated,
            recommendations=recommendations,
            required_inputs=required_framework_inputs(),
            source_weights=self.source_weights,
        )
        self.repository.save_memo(memo)
        memo_path = write_outputs(memo, validated, recommendations)

        # Cached macro views are now stale — drop them so tactical gets fresh.
        try:
            from macro_positioning.integration.endpoints import invalidate_view_cache
            invalidate_view_cache()
        except Exception:
            pass  # cache invalidation is best-effort

        # Regime change detection + optional tactical push.
        # No-op when tactical_webhook_url is not configured; safe always.
        try:
            from macro_positioning.integration.regime_watch import detect_and_push
            regime_result = detect_and_push(theses, memo)
            if regime_result.get("changed"):
                logger.info(
                    "Regime change detected (severity=%s, pushed=%s): %s",
                    regime_result.get("severity"),
                    regime_result.get("pushed"),
                    regime_result.get("changes"),
                )
        except Exception as e:
            logger.warning("Regime detection failed (non-fatal): %s", e)

        return PipelineRunResult(
            documents_ingested=len(normalized),
            theses_extracted=len(theses),
            validated_theses=len(validated),
            recommendations_generated=len(recommendations),
            memo_id=memo.memo_id,
            memo_path=str(memo_path),
        )


def _build_market_provider(context: PipelineContext) -> MarketDataProvider:
    if settings.fred_api_key:
        try:
            fred = FREDMarketDataProvider()
            logger.info("Using FRED live market data provider")
            return fred
        except Exception:
            logger.warning("FRED provider init failed, falling back to static", exc_info=True)
    logger.info("Using static market data provider")
    return StaticMarketDataProvider(context.market_observations)


def build_pipeline() -> PositioningPipeline:
    """Build a pipeline wired to the best available Brain backend."""
    initialize_database(settings.sqlite_path)
    repository = SQLiteRepository(settings.sqlite_path)
    brain = build_brain_client()
    weights = _load_default_source_weights()
    return PositioningPipeline(
        repository=repository,
        brain=brain,
        source_weights=weights,
    )


def _load_default_source_weights() -> dict[str, float]:
    for candidate in (
        settings.base_dir / "config" / "sources.example.json",
        Path("config/sources.example.json"),
    ):
        if candidate.exists():
            try:
                return source_trust_weights(load_source_registry(candidate))
            except Exception:
                logger.warning("Failed to load source registry from %s", candidate, exc_info=True)
    return {}


def main() -> None:
    pipeline = build_pipeline()
    result = pipeline.run(sample_documents(), context=sample_context())
    print(result.model_dump_json(indent=2))


def write_outputs(memo, validated_theses, recommendations) -> Path:
    output_path = settings.base_dir / "data" / "processed" / "latest_memo.md"
    markdown = render_memo_markdown(memo, validated_theses, recommendations)
    return write_memo_markdown(output_path, markdown)


def required_framework_inputs() -> list[str]:
    return [
        "Top trusted experts with channel links and priority order.",
        "Market buckets to support first, such as macro, rates, FX, or commodities.",
        "Available APIs or data subscriptions for social, video, transcripts, and market validation.",
        "Preferred report cadence and alerting rules.",
    ]


if __name__ == "__main__":
    main()

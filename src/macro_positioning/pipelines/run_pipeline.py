from __future__ import annotations

from pathlib import Path

import logging

from macro_positioning.core.models import PipelineContext, PipelineRunResult, RawDocument
from macro_positioning.core.settings import settings
from macro_positioning.db.repository import SQLiteRepository
from macro_positioning.db.schema import initialize_database
from macro_positioning.ingestion.base import normalize_document
from macro_positioning.ingestion.sample_sources import sample_context, sample_documents
from macro_positioning.ingestion.source_registry import load_source_registry, source_trust_weights
from macro_positioning.llm.extractor import HeuristicThesisExtractor, ThesisExtractor
from macro_positioning.market.fred_provider import FREDMarketDataProvider
from macro_positioning.market.providers import MarketDataProvider, StaticMarketDataProvider
from macro_positioning.market.validation import build_recommendations, validate_theses

logger = logging.getLogger(__name__)
from macro_positioning.reports.memo import build_positioning_memo
from macro_positioning.reports.renderers import render_memo_markdown, write_memo_markdown


class PositioningPipeline:
    def __init__(
        self,
        repository: SQLiteRepository,
        extractor: ThesisExtractor,
        source_weights: dict[str, float] | None = None,
        use_gemini: bool = False,
    ) -> None:
        self.repository = repository
        self.extractor = extractor
        self.source_weights = source_weights or {}
        self.use_gemini = use_gemini

    def run(self, documents: list[RawDocument], context: PipelineContext | None = None) -> PipelineRunResult:
        context = context or PipelineContext()
        normalized_documents = [normalize_document(document) for document in documents]
        for document in normalized_documents:
            self.repository.save_document(document)

        # Gather market observations first (needed by both paths)
        provider = _build_market_provider(context)
        observations = provider.gather([])  # Gather all available data
        if not observations and context.market_observations:
            logger.warning(
                "Live market provider returned 0 observations - using %d static context obs.",
                len(context.market_observations),
            )
            observations = list(context.market_observations)

        # Choose synthesis path
        if self.use_gemini:
            theses = self._run_gemini_synthesis(normalized_documents, observations, context)
        else:
            theses = self._run_heuristic_extraction(normalized_documents)

        for thesis in theses:
            self.repository.save_thesis(thesis)

        validated_theses = validate_theses(theses, observations)
        recommendations = build_recommendations(validated_theses)

        memo = build_positioning_memo(
            theses,
            validated_theses=validated_theses,
            recommendations=recommendations,
            required_inputs=required_framework_inputs(),
            source_weights=self.source_weights,
        )
        self.repository.save_memo(memo)
        memo_path = write_outputs(memo, validated_theses, recommendations)

        return PipelineRunResult(
            documents_ingested=len(normalized_documents),
            theses_extracted=len(theses),
            validated_theses=len(validated_theses),
            recommendations_generated=len(recommendations),
            memo_id=memo.memo_id,
            memo_path=str(memo_path),
        )

    def _run_heuristic_extraction(self, documents) -> list:
        """Original per-document keyword extraction."""
        theses = []
        for document in documents:
            theses.extend(
                self.extractor.extract(
                    document_id=document.document_id,
                    source_id=document.source_id,
                    text=document.cleaned_text,
                    published_at=document.published_at,
                    url=document.url,
                )
            )
        return theses

    def _run_gemini_synthesis(self, documents, observations, context) -> list:
        """Send all content to Gemini for holistic macro synthesis."""
        from macro_positioning.llm.gemini_analyzer import GeminiThesisExtractor

        analyzer = GeminiThesisExtractor()
        for doc in documents:
            analyzer.add_document(doc)
        analyzer.set_context(
            observations=observations,
            notes=context.analyst_notes if context else [],
        )

        logger.info("Running Gemini macro synthesis on %d documents + %d observations",
                     len(documents), len(observations))

        try:
            theses = analyzer.synthesize()
            logger.info("Gemini produced %d theses", len(theses))
            return theses
        except Exception as e:
            logger.error("Gemini synthesis failed: %s — falling back to heuristic", e, exc_info=True)
            return self._run_heuristic_extraction(documents)


def _build_market_provider(context: PipelineContext) -> MarketDataProvider:
    """Use FRED when an API key is configured, otherwise fall back to static."""
    if settings.fred_api_key:
        try:
            fred = FREDMarketDataProvider()
            logger.info("Using FRED live market data provider")
            return fred
        except Exception:
            logger.warning("FRED provider init failed, falling back to static", exc_info=True)
    logger.info("Using static market data provider")
    return StaticMarketDataProvider(context.market_observations)


def _has_gemini_credentials() -> bool:
    """Check if the N8N Gemini webhook is configured."""
    return bool(settings.n8n_webhook_url)


def build_pipeline(use_gemini: bool | None = None) -> PositioningPipeline:
    """Build a pipeline instance.

    Args:
        use_gemini: Force Gemini on/off. If None, auto-detect from credentials.
    """
    initialize_database(settings.sqlite_path)
    repository = SQLiteRepository(settings.sqlite_path)
    extractor = HeuristicThesisExtractor()
    weights = _load_default_source_weights()

    if use_gemini is None:
        use_gemini = _has_gemini_credentials()

    if use_gemini:
        logger.info("Pipeline configured with Gemini synthesis engine")
    else:
        logger.info("Pipeline configured with heuristic extraction (no Gemini credentials)")

    return PositioningPipeline(
        repository=repository,
        extractor=extractor,
        source_weights=weights,
        use_gemini=use_gemini,
    )


def _load_default_source_weights() -> dict[str, float]:
    """Load trust weights from the example registry if available."""
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

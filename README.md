# Macro Positioning Analyzer

This repository is a first-pass scaffold for a research system that:

- ingests trusted market commentary from multiple source types,
- normalizes content into a shared document model,
- extracts macro theses, horizons, catalysts, and positioning implications,
- produces auditable synthesis memos for human decision-making.

## What is included

- A FastAPI app with health, ingest, pipeline, and memo endpoints
- A SQLite-backed repository layer for documents, thesis views, and memos
- A source registry format for tracking trusted commentators and feeds
- Source onboarding and credential requirement templates for real source rollout
- A heuristic thesis extractor that works without external model access
- A clean LLM extraction interface for future model integration
- A market-validation framework for expert-vs-market comparison
- A memo generator that summarizes aligned and divergent views

## What is not included yet

- Live source connectors for X, podcast platforms, or web crawling
- Transcript acquisition or speech-to-text
- A vector database or semantic retrieval layer
- Source weighting, hit-rate scoring, or portfolio construction logic
- Authentication, multi-user support, or a frontend dashboard

## Quick start

1. Create a virtual environment and install the package:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

2. Start the API:

```bash
uvicorn macro_positioning.api.main:app --reload
```

3. Run the sample pipeline from Python:

```bash
python3 -m macro_positioning.pipelines.run_pipeline
```

4. Load a source registry in code:

```python
from pathlib import Path
from macro_positioning.ingestion.source_registry import load_source_registry

sources = load_source_registry(Path("config/sources.example.json"))
```

5. Inspect framework input requirements through the API:

```bash
uvicorn macro_positioning.api.main:app --reload
curl http://127.0.0.1:8000/framework/credentials
curl http://127.0.0.1:8000/framework/onboarding-template
```

## Suggested next build steps

1. Add real ingestion connectors for the first 5-10 trusted sources.
2. Replace the heuristic extractor with a model-backed extraction call and citations.
3. Add semantic retrieval with `pgvector` or another vector store.
4. Add a dashboard for current theses, changes, and supporting evidence.
5. Introduce source scoring and explicit invalidation tracking.

## Important implementation note

The current extractor is intentionally conservative and heuristic-driven. It is useful for proving the data flow and memo structure, but it should be replaced with a model-backed extractor before you rely on it for production research.

The current market validation layer is also scaffold-level. It gives us the right interfaces now, so we can plug in real price, macro, and sentiment feeds next without rewriting the pipeline.

## Design principles

- Keep recommendations traceable to source evidence.
- Separate content collection from thesis extraction and synthesis.
- Treat every macro view as time-bounded and subject to invalidation.
- Keep the final system human-in-the-loop for execution decisions.

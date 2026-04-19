# Architecture Notes

## Core flow

1. `source registry`
   A curated list of trusted analysts, podcasts, websites, and social feeds.

2. `ingestion`
   Pull raw content from each source and normalize it into a shared document structure.

3. `thesis extraction`
   Convert raw commentary into structured macro theses with time horizon, direction, risks, and evidence.

4. `synthesis`
   Aggregate overlapping views, identify divergences, and produce a memo for human review.

5. `decision support`
   Present positioning expressions, catalysts, and invalidation triggers without automating execution.

## Initial schema choices

- `documents`
  Raw and cleaned source material with metadata
- `theses`
  Extracted directional claims with evidence and implied positioning
- `memos`
  Time-stamped synthesis output for review and change tracking

## Near-term build priorities

1. Add connectors for the first trusted sources.
2. Add document chunking and source-level citation spans.
3. Replace heuristic extraction with model-backed JSON extraction.
4. Add thesis clustering so repeated views roll into shared themes.
5. Add scoring for freshness, conviction, and source agreement.

## Risk controls

- Always keep source attribution in the output.
- Track `published_at`, `ingested_at`, and `extracted_at` separately.
- Treat identical talking points from related sources as correlated, not fully independent.
- Store invalidation triggers explicitly whenever a source gives them.

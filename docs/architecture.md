# Architecture Notes

> **Last updated:** 2026-05-09
> **Cross-references:** `docs/architecture_overview.md` (full stack diagram), `docs/data_sources.md` (FRED series), `docs/dashboard_design_brief.md` (UI design)

---

## Core flow

```
1. source registry
   Curated list of trusted analysts, newsletters, podcasts, and data feeds.
   Stored in SQLite (sources table) with trust_weight per source.

2. ingestion
   Pull raw content from each source and normalize into NormalizedDocument.
   Connectors: Gmail (macro_positioning.ingestion.gmail_connector),
               RSS/Atom (macro_positioning.ingestion.rss_connector),
               Manual text via CLI (macro_positioning.cli text)

3. market data (FRED)
   FREDMarketDataProvider.gather() pulls 51 series → list[MarketObservation].
   Three classifiers run on this data before synthesis:
     • classify_growth_inflation_quadrant() → GrowthInflationQuadrant
     • compute_fci()                        → FCIResult
     • compute_geopolitical_risk()          → EPURisk
   These produce formatted text blocks injected into the LLM prompt.

4. synthesis (brain)
   brain/synthesis.py assembles the full prompt (documents + FRED + 3 indicator
   blocks + analyst notes + chart reads) and calls the configured LLM backend.
   Default: Gemini 2.5 Pro. Escalation: Claude Sonnet. Fallback: Ollama.
   Output: list[Thesis] (structured JSON parsed from LLM response).

5. persistence
   Thesis objects saved to SQLite via SQLiteRepository.
   Memos saved as PositioningMemo objects.

6. dashboard / decision support
   command_data.build_command_snapshot() aggregates theses, themes, assets,
   and macro indicators into CommandCenterSnapshot (served as JSON).
   desk_data.build_desk_snapshot() assembles MA_DATA for the SPA initial render.
   SPA (web/positioning.jsx) renders the command center.
```

---

## Schema: Core Models

Defined in `src/macro_positioning/core/models.py`.

| Model | Purpose |
|---|---|
| `NormalizedDocument` | Cleaned source material with metadata (source_id, published_at, cleaned_text) |
| `Thesis` | Directional claim with direction, theme, horizon, confidence, assets, catalysts, risks, implied_positioning, evidence |
| `ViewDirection` | Enum: bullish / bearish / neutral / mixed / watchful |
| `ThesisStatus` | Enum: active / stale / invalidated |
| `MarketObservation` | One FRED observation (market, metric, value, as_of, source, interpretation) |
| `Evidence` | Citation linking a thesis to a source document |
| `PositioningMemo` | Synthesized output: consensus_views, divergent_views, suggested_positioning, risks_to_watch, expert_vs_market |

---

## Schema: Dashboard Models

Defined in `src/macro_positioning/dashboard/command_data.py`.

| Model | Purpose |
|---|---|
| `MacroIndicators` | Regime quadrant + FCI + EPU fields; populated from FRED classifiers |
| `ThesisSummary` | Flattened thesis view for the SPA |
| `ThemeCluster` | Aggregated directional counts per theme |
| `AssetBreakdown` | Per-asset aggregation with `dominant_direction`, `confidence`, `asset_class` |
| `ActionableSignal` | Top hero signals (LONG/SHORT/WATCH) with optional `TacticalAnnotation` |
| `CommandCenterSnapshot` | Full snapshot combining all of the above; the `/api/dashboard/command-center` payload |

`AssetBreakdown.asset_class` is derived from a `_THEME_TO_ASSET_CLASS` mapping in `command_data.py`:

```python
_THEME_TO_ASSET_CLASS = {
    "equities": "equities",   "growth": "equities",    "labor": "equities",    "housing": "equities",
    "rates": "rates",         "fiscal": "rates",        "policy": "rates",
    "liquidity": "credit",    "credit": "credit",
    "commodities": "commodities", "energy": "commodities", "inflation": "commodities",
    "fx": "fx", "crypto": "crypto", "geopolitics": "commodities",
}
```

---

## Intelligence Layer: Classifier Details

File: `src/macro_positioning/market/macro_indicators.py`

### Growth/Inflation Quadrant

```python
def classify_growth_inflation_quadrant(observations: list[MarketObservation]) -> GrowthInflationQuadrant
```

- Growth: `A191RL1Q225SBEA` (Real GDP QoQ annualised %). Fallback: `INDPRO`.
  - `> 2.5` → expanding
  - `0 – 2.5` → stable
  - `< 0` → contracting
- Inflation: `T10YIE` (10Y breakeven %). Fallback: `CPIAUCSL`.
  - `> 3.0` → elevated
  - `2.0 – 3.0` → moderate
  - `< 2.0` → subdued
- Quadrant: expanding+elevated=boom, contracting+elevated=stagflation, contracting+subdued=deflation, expanding+subdued=goldilocks. Any "stable" axis → transitional.

### Financial Conditions Index

```python
def compute_fci(observations: list[MarketObservation]) -> FCIResult
```

- Primary: `NFCI` (Chicago Fed — positive = tight, negative = easy). Used directly.
- Supporting: `ANFCI`, `STLFSI4`, `VIXCLS`, `TEDRATE`, `BAMLH0A0HYM2` (normalised via `_FCI_NORMALISE` scale factors).
- Label: `score > 0.3` → tightening, `score < -0.3` → easing, else neutral.
- `primary_driver`: whichever component deviates most from 0.

### Geopolitical Risk (EPU)

```python
def compute_geopolitical_risk(observations: list[MarketObservation]) -> EPURisk
```

- Six series: `USEPUINDXD`, `GEPUCURRENT`, `EPUTRADE`, `EPUFISCAL`, `EPUMONETARY`, `EMVNATSEC`.
- All EPU indices normalised to ~100 historical average by design. Composite = simple average.
- Level: `> 150` → elevated, `< 80` → low, else moderate.
- `dominant_driver`: series with highest absolute deviation from 100.

### Prompt injection

`format_prompt_blocks(observations)` returns a `tuple[str, str, str]` for all three blocks.
Returns `("—", "—", "—")` when observations is empty (heuristic fallback path).

---

## Synthesis Prompt Structure

`MACRO_ANALYSIS_PROMPT` in `brain/prompts.py` (sections in order):

```
## Source Documents
{documents_block}

## FRED Economic Data
{fred_block}

## Macro Regime Quadrant
{regime_quadrant_block}

## Financial Conditions
{fci_block}

## Geopolitical / Policy Risk
{epu_block}

## Additional Market Observations
{market_block}

## Analyst Notes
{notes_block}

## Chart Reads
{chart_block}
```

LLM instruction: "Weight the regime quadrant, FCI, and geopolitical risk explicitly — reference them when justifying direction and confidence on each thesis."

---

## Reliability / Error Handling

- FRED failures: `FREDMarketDataProvider.gather()` catches HTTP/init errors; returns empty list
- Intelligence classifiers: each wrapped in try/except in `_build_macro_indicators()`; returns empty `MacroIndicators()` on any failure
- LLM synthesis: `brain/backends.py` escalates Gemini → Claude → Ollama on failure
- JSON parse failure: logs raw response (first 2000 chars), returns empty `SynthesisResult`
- Tactical unreachable: `CommandCenterSnapshot.tactical_reachable = False`; signals still render

---

## Thesis Deduplication

`_deduplicate_theses()` in `command_data.py` groups theses by their text content (strip whitespace), keeps the most recent extraction, and records `run_count` (how many pipeline runs produced this thesis). This prevents repeated pipeline runs from bloating the command center view.

---

## Near-term Build Priorities (carried forward from improvements_2026_04_05.md, updated)

1. ✅ LLM extractor — `brain/synthesis.py` using Gemini 2.5 Pro
2. ✅ Regime quadrant classifier — `macro_indicators.classify_growth_inflation_quadrant()`
3. ✅ FCI classifier — `macro_indicators.compute_fci()`
4. ✅ EPU geopolitical risk — `macro_indicators.compute_geopolitical_risk()`
5. ✅ Asset-class grouping on /positioning — `AssetBreakdown.asset_class`
6. ⏳ COT data connector (`cot_provider.py`) — Phase C, deferred
7. ⏳ `/positioning/view` endpoint for tactical gate
8. ⏳ Source scoring feedback loop (`/source-scoring/outcome`)
9. ⏳ Freshness decay on `freshness_score` (currently hardcoded 0.9)
10. ⏳ `/journal` view

# Canonical Architecture: Three-Layer Trading Stack

> **Last updated:** 2026-05-09
> **Cross-references:** `docs/architecture.md` (core flow detail), `docs/integration_with_trading_agent.md` (contract spec), `docs/data_sources.md` (FRED series catalogue)

---

## Current Reality vs. Original Plan

The original plan described a three-layer stack with the Brain as a *separate repo* to be built. In practice, the Brain has been built **inside** the `macro-analyzer` repo under `src/macro_positioning/brain/`. This is a pragmatic choice for now — the code is cleanly namespaced and can be extracted later if needed. The tactical executor remains in `Trading-Agent-V1-CODEX` (Node.js).

---

## The Three Layers

```
┌──────────────────────────────────────────────────────────────────┐
│  LAYER 1 — INPUT / INGESTION + BRAIN                             │
│  Repo: macro-analyzer (this repo)                                │
│  Tech: Python / FastAPI / SQLite                                 │
│                                                                  │
│  Sub-packages:                                                   │
│    brain/        — LLM orchestration, synthesis, memo            │
│    ingestion/    — Gmail, RSS, chart screenshots                 │
│    market/       — FRED provider, macro_indicators classifiers   │
│    dashboard/    — FastAPI routes + SPA data payloads            │
│    db/           — SQLite repository                             │
│    integration/  — tactical_client (outbound to executor)        │
│                                                                  │
│  Outputs: Thesis objects, memos, CommandCenterSnapshot           │
└─────────────────────────┬────────────────────────────────────────┘
                          │
                          ↓   HTTP pull (tactical_client.py)
                          │   or future push webhooks
                          │
┌─────────────────────────┴────────────────────────────────────────┐
│  LAYER 2 — TACTICAL EXECUTOR                                     │
│  Repo: Trading-Agent-V1-CODEX                                    │
│  Tech: Node.js / webhook server / Alpaca                         │
│                                                                  │
│  Job: Deterministic gates, execution, lifecycle tracking.        │
│  - Receive directional views from Brain                          │
│  - Apply risk rules (stop/size/invalidation)                     │
│  - Gate against macro confidence tiers                           │
│  - Route to Alpaca (paper/live)                                  │
│  - Track state: watch → trigger → in_trade → tp_zone            │
│  No LLM — deterministic for auditability                         │
└──────────────────────────────────────────────────────────────────┘
                          │
                          │  feedback loop
                          ↓   POST /source-scoring/outcome (planned)
```

---

## Intelligence Layer (added 2026-05)

> **Reference:** Urban Kaoberg (urbankaoberg.com) audit surfaced how their macro-regime and FCI modules are structured. See `docs/data_sources.md §Urban Kaoberg` for full context and the 5 items adopted.

Three structured classifiers in `src/macro_positioning/market/macro_indicators.py` sit between raw FRED data and the LLM synthesis call. They are **pure functions** — `list[MarketObservation] → Pydantic model` — fully testable without network calls.

| Classifier | Output model | Primary series | Fallback |
|---|---|---|---|
| `classify_growth_inflation_quadrant()` | `GrowthInflationQuadrant` | `A191RL1Q225SBEA` (Real GDP QoQ%), `T10YIE` (10Y breakeven) | `INDPRO`, `CPIAUCSL` |
| `compute_fci()` | `FCIResult` | `NFCI` (Chicago Fed composite) | `VIXCLS`, `TEDRATE`, `BAMLH0A0HYM2` normalised |
| `compute_geopolitical_risk()` | `EPURisk` | 6 EPU FRED series avg | — |

**Quadrant matrix:**

| Growth \ Inflation | Elevated (>3%) | Moderate (2–3%) | Subdued (<2%) |
|---|---|---|---|
| Expanding (>2.5%) | boom | transitional | goldilocks |
| Stable (0–2.5%) | transitional | transitional | transitional |
| Contracting (<0%) | stagflation | transitional | deflation |

**Data flow through the intelligence layer:**

```
FREDMarketDataProvider.gather()
        │
        ↓ list[MarketObservation]
        ├──→ classify_growth_inflation_quadrant() → regime_quadrant_block (str)
        ├──→ compute_fci()                        → fci_block (str)
        └──→ compute_geopolitical_risk()          → epu_block (str)
                │
                ↓ three formatted text blocks
        MACRO_ANALYSIS_PROMPT.format(
            ...,
            regime_quadrant_block=,
            fci_block=,
            epu_block=,
        )
                │
                ↓
        LLM synthesis (Gemini 2.5 Pro default / Claude Sonnet escalation / Ollama fallback)
                │
                ↓
        list[Thesis] → SQLite → CommandCenterSnapshot → /api/dashboard/command-center
```

The same FRED observations also populate `MacroIndicators` in `CommandCenterSnapshot`, which is served to the SPA at `/api/dashboard/desk` for the `MacroIndicatorStrip` component.

---

## LLM Stack (Brain Sub-package)

| Task | Backend | Config |
|---|---|---|
| Macro text synthesis | Gemini 2.5 Pro (default) | `MPA_GEMINI_API_KEY` |
| Escalation | Claude Sonnet | `MPA_ANTHROPIC_API_KEY` |
| Local fallback | Ollama | `MPA_OLLAMA_HOST` |
| Chart vision | Gemini 2.5 Flash (multimodal) | same key |

Backend routing lives in `brain/backends.py`. `brain/synthesis.py` calls `generate(backend=...)` which dispatches to the right provider. N8N was considered as an orchestration layer but is not the default path — direct API calls are used.

---

## Dashboard Architecture

The dashboard is a **Single-Page Application** (SPA), not server-rendered HTML.

```
web/index.html          — SPA shell, loads React + Babel from CDN
web/positioning.jsx     — /positioning tab (command center + signals)
web/styles.css          — shared CSS variables + component styles

FastAPI routes:
  GET /                 → 307 redirect → /web/index.html
  GET /positioning      → 307 redirect → /web/index.html
  GET /dev              → 307 redirect → /web/index.html
  GET /api/dashboard/desk         → desk_data.build_desk_snapshot()
  GET /api/dashboard/command-center → command_data.build_command_snapshot()
  GET /api/dashboard/brain/activity → brain activity log
  GET /api/dashboard/sources        → source health
```

Data is injected into `window.MA_DATA` on page load (initial render), then components poll their respective endpoints on a cadence. The old Python HTML-generation pipeline (`output_ui.py`, `tactical_ui.py`, etc.) is still present but redirected — all rendering now happens in React.

---

## Repository Map

| Repo | Role | Tech | Status |
|---|---|---|---|
| `macro-analyzer` | Ingestion + Brain + Dashboard | Python/FastAPI | Active |
| `Trading-Agent-V1-CODEX` | Tactical executor | Node.js | Active |

The `macro-brain` separate repo described in early planning has not been created. Brain logic lives in `src/macro_positioning/brain/`.

---

## Data Flow (Current)

```
macro-analyzer                                   tactical-executor
      │                                                 │
      │  Gmail / RSS / manual notes                    │
      │  ──────────────────────────                    │
      │  FREDMarketDataProvider.gather()               │
      │     → 51 series, 3 classifiers                 │
      │     → regime_quadrant / FCI / EPU blocks       │
      │                                                 │
      │  brain/synthesis.py                            │
      │     → MACRO_ANALYSIS_PROMPT (with blocks)       │
      │     → Gemini 2.5 Pro                           │
      │     → list[Thesis] → SQLite                    │
      │                                                 │
      │  command_data.build_command_snapshot()         │
      │     → CommandCenterSnapshot (+ MacroIndicators)│
      │     → /api/dashboard/command-center (JSON)     │
      │                                                 │
      │  tactical_client.fetch_tactical_snapshot()     │
      │ ──────────────────────────────────────────────▶│
      │      GET /tactical/snapshot                    │
      │ ◀──────────────────────────────────────────────│
      │      {events, setups, configured: true}        │
      │                                                 │
      │  SPA (positioning.jsx)                         │
      │     → MacroIndicatorStrip (regime/FCI/EPU)     │
      │     → ActionableSignals (LONG/SHORT/WATCH)     │
      │     → ThemeCluster heatmap                     │
      │     → AssetBreakdown (grouped by asset_class)  │
```

---

## Contracts Between Layers

### Macro Analyzer → Tactical Executor (implemented)

`tactical_client.py` in `src/macro_positioning/integration/` polls the tactical executor's HTTP API. Contract version: `1.0.0`.

Schema CI pipeline (GitHub Actions):
- `schema-export-check` — verifies schema export matches codebase on every push
- `schema-mirror-pr` — opens a PR in Trading-Agent-V1-CODEX when schema changes
- `schema-drift-check` — blocks merge if the consumer is out of sync

See `docs/integration_with_trading_agent.md` for full endpoint specs.

### Planned (not yet built)

- `GET /positioning/view?asset={ticker}` — per-asset macro gate for tactical
- `POST /source-scoring/outcome` — trade outcome feedback loop

---

## Graceful Degradation

| Failure | Behavior |
|---|---|
| FRED unavailable | Intelligence layer returns empty `MacroIndicators`; synthesis proceeds without blocks (passes `"—"` strings) |
| Tactical executor unreachable | `CommandCenterSnapshot.tactical_reachable = False`; ActionableSignals still render without TacticalAnnotation |
| Gemini unavailable | `brain/backends.py` falls back to Claude Sonnet, then Ollama |
| SQLite locked | Pre-existing issue when a `score run` CLI process holds the DB; kill that process first |

---

## Open Decisions

1. **Extract brain to separate repo** — currently inside macro-analyzer; extract when it needs independent deployment or GPU hosting
2. **COT data connector** (`cot_provider.py`) — Phase C, deferred; CFTC weekly reports, free public domain
3. **Tactical executor rename** — `Trading-Agent-V1-CODEX` → `tactical-executor` (pending)
4. **SSE vs polling** — regime tape currently uses 5-min polling; upgrade to SSE if UX bottleneck
5. **`/journal` view** — designed in `dashboard_design_brief.md` §3.3, not yet built

# Canonical Architecture: Three-Layer Trading Stack

## The Three Layers

```
┌──────────────────────────────────────────────────────────────────┐
│  LAYER 1 — INPUT / INGESTION                                     │
│  Repo: macro-analyzer (this repo — may be renamed "macro-input") │
│  Tech: Python / FastAPI / SQLite                                 │
│                                                                  │
│  Job: Collect, normalize, and stage data. NOT reason about it.   │
│  Inputs:                                                         │
│    - Newsletters (Gmail)                                         │
│    - FRED economic data                                          │
│    - Finnhub news + sentiment                                    │
│    - Google News RSS                                             │
│    - TradingView alerts                                          │
│    - Chart screenshots                                           │
│    - Manual analyst notes                                        │
│  Output: Structured, enriched data packets for the Brain         │
│  Contains: Heuristic pre-filters (keyword tagging for routing)   │
│  No LLM inference here — just ingestion, normalization, staging  │
└─────────────────────────┬────────────────────────────────────────┘
                          │
                          ↓   POST /brain/ingest
                          │
┌─────────────────────────┴────────────────────────────────────────┐
│  LAYER 2 — BRAIN (to be built, new repo)                         │
│  Repo: macro-brain (new)                                         │
│  Tech: Python orchestrator + multiple LLM backends               │
│                                                                  │
│  Job: All the thinking happens here.                             │
│  - Macro text synthesis (reads newsletters + FRED holistically)  │
│  - Chart vision analysis (reads screenshots for patterns/levels) │
│  - Cross-asset reasoning (ties themes together)                  │
│  - Conviction / confidence scoring                               │
│  - Directional calls per asset class                             │
│  Output: Thesis objects, directional views, trade candidates     │
│  Multiple LLMs orchestrated — see "LLM Stack" section            │
└─────────────────────────┬────────────────────────────────────────┘
                          │
                          ↓   POST /tactical/view
                          │
┌─────────────────────────┴────────────────────────────────────────┐
│  LAYER 3 — TACTICAL / EXECUTION (existing repo, needs revamp)    │
│  Current: Trading-Agent-V1-CODEX                                 │
│  Suggested rename: tactical-executor                             │
│  Tech: Node.js / webhook server / Alpaca                         │
│                                                                  │
│  Job: Deterministic gates, execution, lifecycle tracking.        │
│  - Receive Brain's directional views                             │
│  - Apply risk rules (stop/size/invalidation)                     │
│  - Gate against Brain's confidence tiers                         │
│  - Route to Alpaca (paper/live)                                  │
│  - Track state: watch → trigger → in_trade → tp_zone             │
│  - Post outcomes back to Input layer                             │
│  No LLM — stays deterministic for auditability                   │
└──────────────────────────────────────────────────────────────────┘
                          │
                          │  feedback loop
                          ↓   POST /input/outcome
                                    (source scoring)
```

## Why Three Layers

Separating ingestion, reasoning, and execution into independent services:

1. **Each layer uses the right tool** — Python for data/LLMs, Node for execution
2. **Fault isolation** — a bug in the Brain won't break live trading
3. **Independent scaling** — Brain needs GPU; execution needs always-on webhooks
4. **Independent iteration** — swap LLMs without touching execution logic
5. **Each layer has a clean contract** — debuggable, testable, auditable

## LLM Stack (Brain Layer)

Different models for different tasks, orchestrated by the Brain service:

| Task | Model | Why |
|---|---|---|
| Macro text synthesis | Finance-tuned text LLM OR Gemini 2.5 Flash | Holistic reading of newsletters, thesis formation |
| Chart / image analysis | Multimodal LLM (Qwen2.5-VL or Gemini 2.5 Flash) | Pattern recognition, level identification |
| Hawkish/dovish classification | CentralBankRoBERTa (355M) | Fast, specialized Fed language tagging |
| Reasoning / decision | Same text LLM with structured prompts | Synthesizing across themes |
| Embeddings / RAG | Sentence transformers or Gemini embeddings | Retrieval over historical theses, trade memory |

## Repository Map

| Repo | Role | Tech | Status |
|---|---|---|---|
| `macro-analyzer` ([repo](https://github.com/thommi2phones/macro-analyzer)) | Input layer | Python/FastAPI | Exists — needs trim |
| `macro-brain` (TBD) | Brain layer | Python + LLMs | To build |
| `Trading-Agent-V1-CODEX` ([repo](https://github.com/thommi2phones/Trading-Agent-V1-CODEX)) | Tactical/execution | Node.js | Exists — needs revamp + rename |
| `openclaw-pm` (optional extract) | Human PM/accountability | Node/Telegram bot | Separate concern from brain |

## Data Flow

```
macro-analyzer              macro-brain              tactical-executor
      │                          │                          │
      │  POST /brain/ingest      │                          │
      │ ────────────────────────▶│                          │
      │  {newsletters, fred,     │                          │
      │   charts, notes}         │                          │
      │                          │                          │
      │                          │  LLM orchestration       │
      │                          │  - text synthesis        │
      │                          │  - chart vision          │
      │                          │  - reasoning             │
      │                          │                          │
      │                          │  POST /tactical/view     │
      │                          │ ────────────────────────▶│
      │                          │  {direction, conf,       │
      │                          │   horizon, asset}        │
      │                          │                          │
      │                          │                          │ Gate + risk +
      │                          │                          │ execute
      │                          │                          │
      │  POST /input/outcome     │                          │
      │ ◀───────────────────────────────────────────────────│
      │  {trade_id, pnl,         │                          │
      │   attribution}           │                          │
      │                          │                          │
      │ Update source weights    │                          │
```

## Migration Work Required

### Out of macro-analyzer (move to macro-brain)
- `src/macro_positioning/llm/gemini_analyzer.py`
- `src/macro_positioning/llm/chart_analyzer.py`
- The synthesis prompts and LLM orchestration logic

### Stays in macro-analyzer (input layer)
- FRED provider, Gmail connector, RSS connector
- SQLite persistence for raw/normalized data
- Heuristic pre-tagging (keyword routing)
- Dashboard (ops + command center can remain here for the input-side view)

### New in macro-brain (to build)
- LLM orchestrator service
- Model selection / fallback logic
- Synthesis prompts library
- Brain-side dashboard showing active theses + reasoning trail

### Revamp in tactical-executor (current Trading-Agent-V1-CODEX)
- Remove embedded LLM/agent logic (`claude_agent_contract.md` concepts)
- Add consumer for Brain's `/tactical/view` endpoint
- Keep deterministic decision engine + lifecycle
- Extract OpenClaw PM into own repo (or remove)

## Contracts Between Layers

### Brain pulls from Input
`GET /data/pending` — Brain polls for new data packets ready for analysis
`POST /data/ack` — Brain acknowledges consumed packets

### Tactical pulls from Brain
`GET /positioning/view?asset={ticker}` — per-ticker directional view
`GET /positioning/regime` — overall macro regime
`GET /positioning/theses` — active theses with evidence

### Input receives from Tactical
`POST /source-scoring/outcome` — trade outcomes for source weight feedback

## Graceful Degradation

Each layer must work when downstream/upstream is unavailable:

- **Brain down** → Tactical executor uses last-known macro view or defaults to "unknown" (doesn't block)
- **Tactical down** → Brain still produces views; they just don't get acted on
- **Input down** → Brain uses cached data; no new analyses
- **Any layer** can be restarted without cascading failures

## Non-Goals

These are explicitly NOT part of this architecture:

- Shared database between layers
- Shared authentication (each layer has its own)
- Real-time streaming (polling + webhooks are sufficient)
- Unified UI (each layer has its own dashboard; combined view is future work)
- Brain generating trade ORDERS (only views/theses; orders are Tactical's job)

## Open Decisions

1. **When to create `macro-brain` repo** — now vs. after input layer stabilizes
2. **LLM hosting strategy** — API (Gemini via N8N), rented GPU, or GCP Vertex
3. **Tactical rename timing** — rename `Trading-Agent-V1-CODEX` now or keep name
4. **OpenClaw PM** — extract into own repo, absorb into Brain, or deprecate

# Current State

_Last updated: 2026-05-09_

## Active Task

Macro Analyzer is past Phase 6d. Live SPA dashboard at http://127.0.0.1:8000/ shows
real scored watchlist (66 tickers) driven by live yfinance prices, time-weighted
mention extraction, and a real heuristic technical scorer with EMA + multi-horizon
momentum. The data flywheel infrastructure exists (agent_call_log, source_outcomes,
training_corpus/) but no learning queries / model retraining wired yet.

Two parallel work tracks:
1. **Manual input layer** — moved to separate chat session
2. **ML / learning loop** — needs design + build (this session's open scope)

## Progress

### Shipped this session (origin/main)
- [x] Phase 5: production SPA dashboard (Claude Design output) — `9a28ea6`
- [x] Phase 5 fix: align desk_data shapes with mock contract — `8fe1be7`
- [x] Phase 6 slice B: dynamic watchlist (anchors + theme + mentions) + scoring runner — `da526a6`
- [x] Phase 6c: live prices via yfinance + real technical scorer + WAL — `30360e7`
- [x] Phase 6d: time-weighted scoring (signals + prices + score history dScore) — `2ea99c7`

### What's REAL today
- 66-ticker watchlist scored every `score run`, persisted in `trade_scores`
- yfinance daily OHLCV; SQLite `prices` table; `prices fetch` CLI
- Technical scorer reads SMA/EMA/momentum/breakout/RSI per framework §5
- Mention extractor recency-decayed (macro half-life = window length)
- Source-freshness multiplier dampens mentions from cold sources
- dScore (today vs prior pass) shows on hero cards + watchlist
- 263/263 tests passing

### What's STUBBED (explicit by-design)
- liquidity_alignment scorer — neutral 0.5
- sector_theme_strength scorer — neutral 0.5
- volume_flow_confirmation scorer — neutral 0.5 (volume column persisted)
- relative_strength scorer — neutral 0.5
- regime_classifier — keyword-hint stub, not LLM-backed
- narrative_synthesizer — passthrough stub
- chart_vision — passthrough stub (manual input chat owns wiring it
  to Gemini 2.5 Pro via existing `brain/vision.py` path)

### Future agent slot (designed, not built)
- **deep_research** — Perplexity Deep Research / OpenAI deep-research
  for narrative synthesis on the live web. Strict budget guards. NOT
  the same as chart_vision; do not conflate. See DECISIONS 2026-05-09
  "LLM stack" entry.

### Open scope
- [ ] Manual input layer (drag-drop charts/text → brain) — **separate chat**
- [ ] ML / learning loop infrastructure (see "Next Steps" below)
- [ ] Real LLM-backed agents (regime + narrative; burns tokens)
- [ ] Volume + sector_theme scorers (read existing data; no LLM cost)
- [ ] Intraday timeframes (4h/12h) — needs intraday yfinance fetch
- [ ] Deploy macro-analyzer to Render

## Files Touched This Session

**New code:**
- `src/macro_positioning/scoring/` — mention_extractor, watchlist_resolver, runner
- `src/macro_positioning/prices/` — provider (yfinance), fetcher, technicals, symbol_map
- `src/macro_brain/agents/technical_scorer/scorer.py` — real heuristic
- `src/macro_positioning/dashboard/desk_routes.py` — `/api/desk/data` + `/web/data.js`
- `src/macro_positioning/dashboard/desk_data.py` — full MA_DATA snapshot builder
- `web/` — Claude Design SPA (index.html, app.jsx, components.jsx, etc)
- `config/watchlist.json` — 41 anchor tickers across all macro sectors
- `data/decisions.json` — 14 architectural decisions

**Modified:**
- `src/macro_positioning/db/schema.py` — added prices, agent_call_log, decisions, +6 framework tables; WAL mode enabled
- `src/macro_positioning/cli.py` — added `sources`, `score run`, `prices fetch` subcommands
- `src/macro_brain/orchestrator/composer.py` — wired technical_scorer
- `src/macro_positioning/api/main.py` — StaticFiles mount for SPA + redirects
- `src/macro_positioning/dashboard/router.py` — old routes 307-redirect to SPA
- `pyproject.toml` — added yfinance

**Deleted:** old per-view HTML modules — `output_ui.py`, `dev_ui.py`, `tactical_ui.py`, `terminal_hub.py`, `guide_ui.py`

## Key Context

**Tests:** 263/263 passing. Run with: `uv run pytest -q`
**Server:** `cd /Users/thom/Documents/Personal/Code\ Projects/Macro\ Analyzer && uv run uvicorn macro_positioning.api.main:app --host 127.0.0.1 --port 8000`
**Live URL:** http://127.0.0.1:8000/ (redirects to /web/index.html)
**Package manager:** Always `uv`.
**SQLite:** WAL mode enabled. Concurrent reader (server) + writer (CLI) coexist.

**Hot-fetch + score loop:**
```
uv run python -m macro_positioning.cli prices fetch --watchlist
uv run python -m macro_positioning.cli score run
# Server reload not needed — data.js is server-rendered each request
```

**SPA contract (web/HANDOFF.md):** the SPA reads `window.MA_DATA` set by
`/web/data.js` (dynamically rendered by `desk_routes.py` from `desk_data.py`).
16 sections; field names MUST match `web/data.mock.js` exactly or React throws.

**Sister-session artifacts (not from this session):**
- `src/macro_positioning/market/macro_indicators.py` — regime/FCI/EPU classifiers
- `MacroIndicatorStrip` in `web/positioning.jsx`
- These work; haven't touched them this session.

**Two-repo split was reversed (D-2026-05-09-015):** brain code lives at
`src/macro_brain/` inside this repo. Old `thommi2phones/macro-brain` GitHub
repo is archived (read-only, recoverable via `gh repo unarchive`).

**Three dev-side Claude subagents:** `.claude/agents/{thesis,framework,app}/CLAUDE.md`.
This session was Application Agent territory.

**North-star principle (D-2026-05-08-010):** fine-tuning-ready from day one.
Every LLM call must satisfy `docs/logging_contract.md` (write to `agent_call_log`).
`training_corpus/` accumulates JSONL examples.

## Next Steps — ML / Learning Loop (PRIORITY)

User explicitly called out: "the learnings on author accuracy etc etc - the
retraining of the models and everything on that end as well." Concrete work:

### Already wired (collecting data, no consumer yet)
- `agent_call_log` table — every LLM call's input/output/context/cost
- `source_outcomes` table — per-source per-trade attribution (empty until first close)
- `trade_scores` history — score-per-asset-over-time queryable
- `training_corpus/` directory — JSONL accumulation, .gitignored

### Not yet wired — to build
1. **Source / author accuracy aggregator** — query `source_outcomes` →
   per-source 30/90d net attribution → feeds `sourceLeaderboard` on `/journal`
   (currently empty). One SQL query + desk_data wire-up.
2. **Score-to-outcome correlation** — Spearman ρ between
   `adjusted_total_score` at entry and realized `pnl_percent` at close. Per
   sub-component too. Surface in `/dev` cost/quality panel.
3. **Regime classifier accuracy** — when classifier said "X" in May, did
   Jun/Jul actually behave like X? Backtest harness, monthly rollup.
4. **Mention extraction precision** — ticker auto-promoted via mentions →
   was it scored well after? Did it produce a trade? Outcomes?
5. **Per-call quality scoring** — for each `agent_call_log` row, was the
   output downstream-confirmed? Add `quality_score` column + manual or
   heuristic backfill.
6. **Retraining triggers** — at what corpus size / time interval do we kick:
   - First trained regime classifier (Phase 8 — needs labeled FRED + price history)
   - First fine-tuned narrative_synthesizer (≥ N high-quality call records)
   - First learned scoring weight adjustments per regime
7. **Model versioning** — when a trained classifier ships, `agent_call_log`
   row needs `model_version` so we can A/B old vs new

### Lower-priority next-up (non-ML)
- Volume + sector_theme heuristic scorers (read existing data; no LLM cost)
- Intraday timeframes (4h/12h) — needs intraday yfinance fetch +
  per-timeframe feature compute
- LLM-backed regime + narrative agents (Phase 6e — burns tokens)

## Blocked / Waiting

See OPEN-QUESTIONS.md.

# Current State

_Last updated: 2026-05-09 (manual-input Piece 1 shipped in worktree, awaiting merge)_

## Active Task

Macro Analyzer is past Phase 6d. Live SPA dashboard at http://127.0.0.1:8000/ shows
real scored watchlist (66 tickers) driven by live yfinance prices, time-weighted
mention extraction, real heuristic technical scorer, **plus four heuristic scorers
(volume/sector/RS/liquidity) replacing the neutral-0.5 stubs.** Score spread now 14..72.

Data flywheel: `agent_call_log`, `source_outcomes`, `training_corpus/` collect data;
**`learning/` package (items 1–3) now consumes** — source attribution dual-lens,
score-outcome Spearman ρ, mention precision@k. Surfacing into SPA still PM-side todo.

Coordination model: this repo runs PM + multiple parallel worker chats. Briefs at
`.claude/context/briefs/`. PM owns schema, `desk_data.py` SPA contract, and
`.claude/context/*` upkeep; workers own feature implementation in declared territory.

Active worker chats:
1. **Manual input layer** — Piece 1 **SHIPPED** in worktree `intelligent-colden-e8af58`,
   not yet merged to main. Verified live in browser. Plan at
   `~/.claude/plans/manual-input-layer-also-hazy-island.md`. Piece 2 (Gemini
   chart vision) deferred to a future session — stub at `manual/vision.py`
   raises `NotImplementedError("enabled in Piece 2")`.
2. **LLM agents** (regime + narrative) — worktree spun up, not yet started.

Recently shipped worker hand-backs (just merged):
- **Heuristic scorers** — `7eb7c73` merged via `claude/elegant-shirley-b652e2`.
- **ML learning loop items 1–3** — `85e186a` merged via `claude/gallant-albattani-b210c8`.

## Manual Input Layer — Piece 1 SHIPPED (worktree, pre-merge)

**Branch:** `claude/intelligent-colden-e8af58` · last commit on this work
is uncommitted on disk in worktree `.claude/worktrees/intelligent-colden-e8af58/`.

**What landed end-to-end (verified in browser via Claude-in-Chrome):**
- New SPA route `/04 inbox` with drop-zone, paste-from-clipboard, metadata
  form (ticker, side, conviction 1–5, timeframe 1H/4H/1D/1W, note,
  author + channel + channel_type), preview card, and "Recent drops"
  history table with pending-vision badge.
- API: `POST /api/manual/preview` (no persistence), `POST /api/manual/ingest`
  (multipart, optional file), `GET /api/manual/inputs`, `GET /api/manual/authors`.
- Schema: `input_authors` table + 4 nullable cols on `documents`
  (`author_id`, `user_metadata_json`, `attachment_path`,
  `extracted_features_json`). Idempotent ALTER via PRAGMA table_info check.
- Backend package `src/macro_positioning/manual/`: models, authors, chat_parser
  (heuristic only), processor, vision (Piece 2 stub).
- Pre-tagger + mention_extractor reused unchanged. `config/source_routing.json`
  now maps `manual` → `[narrative_synthesizer, regime_classifier, sector_theme_scorer, technical_scorer]`.
- File storage: `uploads/charts/YYYY-MM/{uuid}.{ext}` (relative to base_dir).
- New dep: `python-multipart>=0.0.9` in `pyproject.toml`.
- Author slug format: `{channel-slug}:{display-slug}` e.g. `bwatch-chat:capo`.
  `input_authors.author_id` is the primary key; submission count is computed
  by joining `documents` on `author_id`.
- 263/263 tests still pass.

**Vendoring decision (changed from plan):** instead of moving 978MB
`trading_agent/` wholesale into `vendor/`, I copied only **2.3MB of source**
(excluded `dashboard/node_modules`, `trade_images`, `data_cache`, `logs`,
`.git`). Saved as `vendor/trading_agent/` with `VENDORED.md` documenting
provenance. Original `trading_agent/` left intact at sibling path; user
can clean up later.

**Foundational seed corpus relocated:** the 392 `trade_images/` (142MB,
the trading_agent's chart-vision baseline) copied to
`manual_entry/baseline_seed/` (root of main repo, not in worktree). Folder
renamed by user from "Manual Entry" → `manual_entry` for code-friendliness.
README at `manual_entry/README.md`. **Piece 2 bootstrap plan:** drain these
images through `/api/manual/ingest` programmatically, attribute to synthetic
author `archive:trading_agent_baseline`. **Not yet wired** — needs Piece 2.

**Piece 2 todo (next session — single-function flip):**
1. Implement `manual/vision.py::analyze_manual_chart()` — currently raises
   `NotImplementedError`. Wire to existing `brain/vision.py` Gemini path,
   feed `config/manual_chart_framework.md` (already copied) as the prompt,
   parse response into `TradeRecord` (model already defined in `manual/models.py`).
   Wrap the call in `logging_wrapper` per logging contract.
2. Build a worker that drains `documents` rows where
   `tags_json.pending_vision = true`, calls `analyze_manual_chart`, writes
   the result to `extracted_features_json`, clears the flag.
3. Build the bootstrap script for `manual_entry/baseline_seed/` →
   `/api/manual/ingest`.

**Per-author hit-rate tracking (deferred):** the schema supports it
(`input_authors.author_id` foreign-keyed via `documents.author_id`), but
needs closed trades + `source_outcomes` joins. Wire after the ML learning
loop has trade outcomes flowing.

## Progress

### Shipped this session (origin/main)
- [x] Phase 5: production SPA dashboard (Claude Design output) — `9a28ea6`
- [x] Phase 5 fix: align desk_data shapes with mock contract — `8fe1be7`
- [x] Phase 6 slice B: dynamic watchlist (anchors + theme + mentions) + scoring runner — `da526a6`
- [x] Phase 6c: live prices via yfinance + real technical scorer + WAL — `30360e7`
- [x] Phase 6d: time-weighted scoring (signals + prices + score history dScore) — `2ea99c7`
- [x] Macro intelligence layer: regime quadrant + FCI + EPU + COT into prompt + SPA strip — `cbfb3d4`
- [x] Worker-chat briefs + PM/worker split — `12f5a46`
- [x] Heuristic scorers (volume_flow, sector_theme, relative_strength, liquidity) — `7eb7c73`
- [x] ML learning loop items 1–3 (source attribution, score-outcome ρ, mention precision) — `85e186a`

### What's REAL today
- 66-ticker watchlist scored every `score run`, persisted in `trade_scores`
- yfinance daily OHLCV; SQLite `prices` table; `prices fetch` CLI
- Technical scorer reads SMA/EMA/momentum/breakout/RSI per framework §5
- Mention extractor recency-decayed (macro half-life = window length)
- Source-freshness multiplier dampens mentions from cold sources
- dScore (today vs prior pass) shows on hero cards + watchlist
- 364/364 tests passing
- Live score spread: 14..72 across 66 tickers (real per-ticker variance from
  volume_flow + relative_strength; theme + liquidity fall back to neutral
  where input data missing)
- `learning/` package: source attribution dual-lens (closed-trade P&L +
  per-mention forward returns), Spearman ρ score-outcome correlation,
  mention precision@k. Surfaced via CLI: `learning {attribution,signals,
  signal-history,correlation,mention-precision}`. Not yet on the SPA.

### What's STUBBED (explicit by-design)
- regime_classifier — keyword-hint stub, not LLM-backed (llm-agents worker)
- narrative_synthesizer — passthrough stub (llm-agents worker)
- chart_vision — passthrough stub (manual input chat owns wiring it
  to Gemini 2.5 Pro via existing `brain/vision.py` path)
- `_heuristic_log.with_log()` is a no-op shim. Pending PM-side schema
  decision: add `agent_call_log.call_type` discriminator so heuristic
  rows don't pollute the LLM training filter.

### Future agent slot (designed, not built)
- **deep_research** — Perplexity Deep Research / OpenAI deep-research
  for narrative synthesis on the live web. Strict budget guards. NOT
  the same as chart_vision; do not conflate. See DECISIONS 2026-05-09
  "LLM stack" entry.

### Open scope
- [x] Manual input layer Piece 1 — capture + DB + UI shipped (worktree pre-merge)
- [ ] Manual input layer Piece 2 — Gemini chart vision + baseline_seed bootstrap
- [ ] LLM agents (regime + narrative on Gemini) — worker brief + worktree ready,
      not started. Brief: `.claude/context/briefs/llm-agents.md`
- [ ] ML / learning loop items 4–7 (quality_score, regime accuracy, retraining
      triggers, model_version) — items 4 + 7 need PM schema additions first
- [ ] Surface `learning/` outputs into SPA (`sourceLeaderboard` on `/journal`,
      correlation panel on `/dev`) — PM job, not worker
- [ ] Intraday timeframes (4h/12h) — needs intraday yfinance fetch
- [ ] Render deployment + mobile-responsive SPA pass — POC target ~2 weeks,
      mobile usable ~1 month (~30% interface time). Stick with Render
      (D-2026-05-08-003); reject Vercel (would force SQLite→Postgres + cron rewrite)
- [ ] `agent_call_log.call_type` discriminator (heuristic vs LLM) — schema
      change PM owes the heuristic-scorers worker

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

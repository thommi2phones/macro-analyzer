# Parallel Workstreams — Phase 1 Build

Multi-agent development plan for Phase 1 of the macro-analyzer. Four
streams run in parallel on separate branches so 3-4 Claude/Codex instances
can work simultaneously without stepping on each other.

---

## Quick Reference

| Stream | Owner | Branch | Scope |
|---|---|---|---|
| **A** — Ingestion | Claude #1 or Codex | `stream-a-ingestion` | `src/macro_positioning/ingestion/**`, `src/macro_positioning/db/**` |
| **B** — Brain | Claude #2 | `stream-b-brain` | `src/macro_positioning/brain/**` |
| **C** — Dashboard | Claude #3 | `stream-c-dashboard` | `src/macro_positioning/dashboard/**` |
| **D** — Integration + Ops | Codex or Claude #4 | `stream-d-integration` | `src/macro_positioning/integration/**`, deploy configs |

All streams target `main` via PR merge once their scaffold → implementation
is complete and passes tests.

---

## Stream A — Ingestion

**Goal**: Real data flowing into the pipeline.

### Scaffolded files (done — ready to implement)

- `src/macro_positioning/ingestion/personal_gmail.py` — personal Gmail connector with OAuth, separate from any shared project Gmail. Includes `print_setup_instructions()` for manual OAuth setup walkthrough.
- `src/macro_positioning/ingestion/finnhub_connector.py` — per-ticker news + sentiment (free 60/min)
- `src/macro_positioning/ingestion/google_news_rss.py` — broad macro topic feeds (no API key)
- `src/macro_positioning/ingestion/fmp_connector.py` — historical OHLCV (free 250/day)
- `src/macro_positioning/ingestion/scheduler.py` — cron-style daily/weekly runs

### Tasks
1. **Personal Gmail OAuth flow** — complete `_load_credentials()`, `get_gmail_service()`, `fetch_newsletters()`, `fetch_and_persist()` in `personal_gmail.py`
2. **Gmail end-to-end wiring** — `fetch_and_persist` must normalize + dedup + save to SQLite
3. **Finnhub connector** — implement `fetch_company_news`, `fetch_general_news`, `fetch_news_sentiment`
4. **Google News RSS** — implement `fetch_query`, `fetch_topic`, `fetch_all_macro_topics` using existing `rss_connector.py` as a base
5. **FMP connector** — implement `fetch_historical_prices`, `fetch_technical_indicator`
6. **Scheduler** — add `apscheduler` to `pyproject.toml`, implement `run_cron()`, wire all morning_run steps
7. **Dedup across all sources** — unique constraint on documents table, tested re-run safety

### Does not touch
- `src/macro_positioning/brain/**`
- `src/macro_positioning/dashboard/**`
- `src/macro_positioning/integration/**`

### New dependencies
- `google-auth`, `google-auth-oauthlib`, `google-api-python-client` (Gmail)
- `apscheduler` (scheduling)
- `feedparser` (RSS — may already be satisfied by existing `rss_connector.py`)

---

## Stream B — Brain

**Goal**: Real multi-model LLM reasoning with observability.

### Scaffolded files (done — ready to use)

- `src/macro_positioning/brain/client.py` — `BrainClient` interface + factory
- `src/macro_positioning/brain/backends.py` — Gemini, Anthropic, Ollama, N8N adapters
- `src/macro_positioning/brain/synthesis.py` — macro text synthesis, backend-agnostic
- `src/macro_positioning/brain/vision.py` — chart vision, multimodal
- `src/macro_positioning/brain/observability.py` — SQLite telemetry for every brain call
- `src/macro_positioning/brain/momentum.py` — FRED series z-scores + trend tags
- `src/macro_positioning/brain/prompts.py` — centralized prompts
- `src/macro_positioning/brain/heuristic.py` — deterministic fallback

### Tasks
1. **First live synthesis** — set `MPA_GEMINI_API_KEY` in `.env`, run `pipeline.build_pipeline().run([...])` with a real newsletter doc, confirm theses come back
2. **Retry + backoff** — wrap `generate_*` calls with tenacity retry decorator
3. **Cached synthesis** — cache `SynthesisResult` in SQLite so `/positioning/view` doesn't refire full synthesis on every tactical gate call (invalidate on new documents)
4. **Wire momentum context into synthesis** — call `compute_momentum_context()` before synthesis, pass results into the prompt via a new `momentum_block` placeholder
5. **Multi-model ensemble** — option to run primary + escalation in parallel and vote on disagreements (use `escalate=True` param)
6. **Cost/token tracking** — extend `BrainCallRecord` with token counts + estimated USD cost
7. **Prompt versioning** — allow A/B testing two prompts side-by-side via settings

### Does not touch
- `src/macro_positioning/ingestion/**`
- `src/macro_positioning/dashboard/**`
- `src/macro_positioning/integration/**`

---

## Stream C — Dashboard

**Goal**: Operator can see what the Brain is doing.

### Scaffolded files (done — endpoints ready for frontend)

- `src/macro_positioning/dashboard/brain_panel.py` — JSON endpoints:
  - `GET /api/dashboard/brain/activity` — last N brain calls + stats
  - `GET /api/dashboard/brain/stats` — aggregate metrics
  - `GET /api/dashboard/brain/reasoning` — latest theses with source weights
  - `GET /api/dashboard/sources` — source weights table

### Tasks
1. **Brain Activity panel** — add to `templates.py`, consume `/api/dashboard/brain/activity`, show last 10 calls with: timestamp, call_type, backend, latency, success, token counts
2. **Reasoning Trail panel** — expandable tree: thesis → evidence → source → source weight
3. **Chart Upload widget** — file input → POST to `/charts/analyze` → render structured read
4. **Source Scoring panel** — table sortable by weight/wins/losses, visual trust bar
5. **Integration Status panel** — shows: Is tactical hitting us? (count of `/positioning/view` calls from `brain_calls` proxy), latest outcome reports, contract version compatibility
6. **Mobile responsive** — phone-friendly layouts for all panels (for checking on the go)

### Does not touch
- `src/macro_positioning/brain/**` (except reading from observability)
- `src/macro_positioning/ingestion/**`

---

## Stream D — Integration + Ops

**Goal**: Both repos talking live in production.

### Scaffolded files (done — ready to extend)

- `src/macro_positioning/integration/source_weights.py` — full CRUD + adjustment rules
- `src/macro_positioning/integration/regime_watch.py` — snapshot + change detection + push webhook
- `src/macro_positioning/integration/endpoints.py` — now wired to actually update source weights on outcome POST

### Tasks
1. **Deploy macro-analyzer** — pick Render / Railway / Fly.io, deploy so it's reachable by the tactical-executor on Render
2. **Set env in tactical Render** — `MACRO_ANALYZER_URL=https://...`
3. **End-to-end live test** — fire a real TradingView alert, verify macro gate applied, verify outcome POST lands, verify source weight updates
4. **Regime change push** — hook `detect_regime_change()` into `PositioningPipeline.run()`; if change detected, fire to tactical webhook
5. **Macro view caching** — cache `/positioning/view` responses in SQLite for 5 min to reduce re-compute
6. **In tactical-executor repo**: cache macro view at entry time (currently fetches at outcome time — see `webhook/macro_integration.js` buildOutcomeReport flow)
7. **In tactical-executor repo**: dashboard panel showing macro gate status per setup
8. **Schema version CI check** — GitHub Action that compares `integration/macro_schema.json` in both repos, fails CI if they drift

### Does not touch
- `src/macro_positioning/ingestion/**`
- `src/macro_positioning/brain/**`
- `src/macro_positioning/dashboard/**` (except integration status panel, which is Stream C)

---

## Coordination Rules

### 1. Branch discipline

- Each stream works ONLY on its named branch
- Never commit directly to `main`
- When a task is done, open a PR: `stream-{letter}-description`
- Keep commits atomic — one task per commit where possible
- Push regularly so mobile-Claude / other sessions can see progress

### 2. Shared files (READ-ONLY across streams)

These files can be READ but NOT MODIFIED concurrently. If your stream needs
to change one of these, pause and coordinate:

- `src/macro_positioning/core/models.py`
- `src/macro_positioning/core/settings.py`
- `src/macro_positioning/api/main.py` (additive only — new endpoints OK, don't change existing)
- `src/macro_positioning/pipelines/run_pipeline.py` (Stream A + B may both need changes; coordinate)
- `data/checklist.json`
- `README.md`
- `pyproject.toml` (for adding deps — coordinate so changes don't collide)

### 3. File ownership matrix

| Stream | Owns (modify freely) | Read-only |
|---|---|---|
| A | `ingestion/`, `db/` (additions to repository) | everything else |
| B | `brain/` | everything else |
| C | `dashboard/` | `brain/observability.py` (read only for the panels) |
| D | `integration/`, `scripts/`, deploy configs | everything else |

### 4. Test discipline

Each stream writes its own tests:
- Stream A: `tests/test_personal_gmail.py`, `tests/test_finnhub.py`, etc.
- Stream B: `tests/test_brain_backends.py`, `tests/test_synthesis.py`, `tests/test_observability.py`
- Stream C: `tests/test_brain_panel.py`
- Stream D: `tests/test_source_weights.py`, `tests/test_regime_watch.py`

Never touch another stream's test file.

### 5. New dependencies

Adding a dep requires updating `pyproject.toml`. Since multiple streams may
want this, coordinate. Preferred pattern:
- Stream lead adds deps to `pyproject.toml` in a FIRST commit (doc only)
- Other streams pull the updated branch before starting work

### 6. Merge order suggestion

Order that minimizes conflicts when merging back to main:
1. Stream B first (brain scaffolding is foundation)
2. Stream D (integration contracts stabilize)
3. Stream A (depends on B for brain calls in pipeline)
4. Stream C (consumes B and D APIs)

---

## Kickoff Prompts

Use these exact prompts to launch each agent:

### Claude #1 — Stream A (Ingestion)
> You are working on the macro-analyzer repo, Stream A (Ingestion).
> Your branch is `stream-a-ingestion`. Read `docs/workstreams.md` for
> full context. Your scope is `src/macro_positioning/ingestion/**` and
> `src/macro_positioning/db/**` ONLY. Do NOT modify `brain/`, `dashboard/`,
> or `integration/`. First task: complete the personal Gmail OAuth flow
> in `ingestion/personal_gmail.py` (currently scaffolded, needs implementation).
> Run `python -m macro_positioning.ingestion.personal_gmail` to see setup
> instructions. Commit to `stream-a-ingestion` only.

### Claude #2 — Stream B (Brain)
> You are working on the macro-analyzer repo, Stream B (Brain).
> Your branch is `stream-b-brain`. Read `docs/workstreams.md` for
> full context. Your scope is `src/macro_positioning/brain/**` ONLY.
> First task: run the first live end-to-end synthesis test. Set
> `MPA_GEMINI_API_KEY` in `.env`, then write a test script that feeds
> 2-3 real newsletter samples into the pipeline and confirms Gemini 2.5 Pro
> returns valid theses. Log the call to brain_calls table. Commit to
> `stream-b-brain` only.

### Claude #3 — Stream C (Dashboard)
> You are working on the macro-analyzer repo, Stream C (Dashboard).
> Your branch is `stream-c-dashboard`. Read `docs/workstreams.md` for
> full context. Your scope is `src/macro_positioning/dashboard/**` ONLY.
> First task: add a "Brain Activity" panel to the command center that
> queries `/api/dashboard/brain/activity` and shows the last 10 brain
> calls with timestamp, backend, model, latency, success status. The
> endpoint is already wired and returns data. Commit to `stream-c-dashboard`
> only.

### Codex / Claude #4 — Stream D (Integration + Ops)
> You are working on both macro-analyzer and Trading-Agent-V1-CODEX repos,
> Stream D (Integration + Ops). In macro-analyzer your branch is
> `stream-d-integration`. Read `docs/workstreams.md` for full context.
> First task: deploy macro-analyzer to a public URL (Render or Railway
> recommended). Set up a PR preview workflow. Then update the tactical
> Render env with `MACRO_ANALYZER_URL`. Run an end-to-end test by firing
> a real TradingView alert and confirming the macro gate is applied.

---

## Status Tracking

Live status in `data/checklist.json` — each stream has tasks prefixed
`stream-a-`, `stream-b-`, etc. Dashboard `/dashboard/ops` shows progress.

---

## When a Stream Completes

1. Run the full test suite — must be all-green
2. Open a PR to `main` with title `Stream X: [description]`
3. Update `docs/workstreams.md` with ✅ on completed tasks
4. Mention any new dependencies, breaking changes, or migration notes
5. Merge on approval
6. Delete the branch

---

## When Streams Conflict

If two streams genuinely need to modify the same file:

1. Stop work on both sides
2. Open a GitHub issue describing the conflict
3. Decide which stream owns the change (usually the more specialized one)
4. Other stream rebases on the change once merged

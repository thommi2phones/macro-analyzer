# Worker brief: Manual input layer

You are a worker chat in the Macro Analyzer project. PM coordinates; you implement inside a declared file territory.

> **Note:** this chat is already in flight in a separate session as of 2026-05-09. This brief is the kickoff template / refresher in case the session needs to be respawned.

## Orientation (do this first)

Read in order:
1. `.claude/context/STATE.md` — see the chart_vision stub callout
2. `.claude/context/DECISIONS.md` — especially the 2026-05-09 LLM stack entry: **Gemini 2.5 Pro via `src/macro_brain/vision.py`**, do NOT introduce Perplexity / OpenAI here
3. `.claude/agents/app/CLAUDE.md`
4. `docs/logging_contract.md` — every Gemini call writes to `agent_call_log`
5. `src/macro_brain/vision.py` — existing Gemini multimodal client; reuse it
6. `web/` — Claude Design SPA; understand how `window.MA_DATA` is populated before designing the upload UI

## Scope

Build the human-in-the-loop input path. User drops a chart image (or pastes a block of text) into a UI; backend runs `chart_vision` (Gemini) on the image, extracts text content, persists results, surfaces them on the dashboard.

### Three flows

1. **Chart drop** — drag-drop image → POST to `/api/manual/chart` → Gemini multimodal call → returns: detected ticker, timeframe, S/R levels, trendlines, indicator state, structural notes
2. **Text drop** — paste newsletter/note text → POST `/api/manual/text` → run existing mention extractor + tagger → persist to `mentions` with `source='manual'`
3. **Review queue** — surface drops in a `/manual` route on the SPA so user can confirm/edit/delete before they enter scoring

## File territory (yours to edit)

- `src/macro_brain/agents/chart_vision/` — replace the stub with real Gemini wiring (reusing `vision.py`)
- `src/macro_positioning/api/manual_routes.py` (new) — FastAPI routes for the two POST endpoints + GET for review queue
- `src/macro_positioning/api/main.py` — mount the manual_routes router
- `web/manual.jsx` (new) — drag-drop UI + review queue component
- `web/app.jsx` — add `/manual` route
- `tests/macro_brain/agents/test_chart_vision.py` — mock Gemini, assert output shape
- `tests/macro_positioning/api/test_manual_routes.py`

## Off-limits (escalate to PM)

- `src/macro_positioning/db/schema.py` — likely need a `manual_drops` table; ASK with column spec
- `src/macro_positioning/dashboard/desk_data.py` — manual data flowing into the main dashboard is a PM step
- `.claude/context/*`
- Other agent dirs (heuristic, regime, narrative — separate worker chats)

## Done criteria

- User can drag a PNG/JPG into `/manual`, see Gemini's extraction render in <10s
- User can paste text, see mention extraction render
- Items appear in a review queue with confirm/delete actions
- Confirmed drops persist to DB and become visible to the score runner on next pass
- All Gemini calls write `agent_call_log` rows with prompt_version + cost_usd
- Tests pass (mock Gemini); no real API calls in tests
- Error states: bad image format, Gemini timeout, oversized file — handled with user-facing messages

## Hand-back format

```
SHIPPED: manual input layer
Branch: claude/<slug>
Commits: <list>
Tests: <count> new
Demo flow: <screenshots or description of a chart drop end-to-end>
Schema requests: <manual_drops table spec>
Open questions: <UI decisions PM should ratify>
```

## Conventions

- `uv` for everything
- Gemini 2.5 Pro only; reuse `src/macro_brain/vision.py`
- Logging contract is non-negotiable
- Image upload size cap (5MB suggested) enforced server-side
- Files NOT persisted to disk if possible — pass bytes straight to Gemini; only persist the extraction
- `.claude/context/*` edits are PM-only — flag schema additions to PM, don't edit context files yourself

---

## Refinement queue (post-Piece-1)

This chat is long-lived. After Piece 1 lands, work the queue below in order
unless PM redirects. Each item is its own commit + hand-back.

### R1 — Bulk chart drop for one trade idea (per-image timeframe + role)

One drop = one trade idea = N chart images. Trade-idea metadata is shared;
chart fields are per-image.

**Schema (already added by PM, 2026-05-09):**
- `manual_chart_attachments(attachment_id PK, document_id FK, attachment_path,
  timeframe, role, note, order_index, created_at)` — index on (document_id,
  order_index). FK → `documents`. Append-only; supersedes the flat
  `documents.attachment_paths_json` (which stays populated for back-compat).

**Shared (trade-idea level on the documents row):** ticker, side,
source_author, source_channel, blurb, conviction.

**Per-image (one row in manual_chart_attachments):**
- `timeframe` (required) — enum 1H/4H/1D/1W, extensible via config
- `role` (optional) — free-text but seed taxonomy chips: `context`, `setup`,
  `entry`, `invalidation`, `target`. User picks a chip OR types their own.
- `note` (optional) — short per-image annotation
- `order_index` — preserves user's drag-reorder

**UX:**
- Drag-drop accepts multiple files in one event
- Preview strip: per-thumbnail timeframe selector + role chip-picker + note field
- Single shared-metadata form sits above the strip
- Reorderable thumbnails; remove individually before submit
- Submit creates one document row + N attachment rows in one transaction

**Vision (Piece 2 readiness):**
- Each attachment gets its own `chart_vision` call
- Pass `timeframe` + `role` into the prompt so the model adapts (a `stop logic`
  close-up gets a different rubric than a `context` zoom-out)
- All N call_log rows share the same `attributed_setup_id` (parent document id)

**NOT in scope:**
- Auto-dedup across drops — duplicate tickers are fine
- Mixing different trade ideas in one drop — make two drops
- Auto-detecting timeframe from pixels (vision can guess; user override always wins)

### R2 — Piece 2: Gemini chart vision wire-up

Flip `src/macro_positioning/manual/vision.py` from `NotImplementedError` to
real Gemini calls. Reuse `brain/vision.py`. Per-attachment, prompt includes
`role` + `timeframe`. Output schema from `config/manual_chart_framework.md`.

### R3 — Baseline seed corpus drain

Drain `manual_entry/` (142MB of historical chart screenshots) into `documents`
+ `manual_chart_attachments` via a one-shot CLI: `python -m
macro_positioning.cli manual ingest-seed`. Inspect filenames for ticker hints;
default timeframe to 1D when unknown; mark drops with `source_author='seed'`
so they're separable in attribution.

### R4 — Inbox → scoring loop confirmation

Verify confirmed drops actually feed the next `score run` cleanly: extracted
ticker enters the watchlist, mention extraction picks up the blurb, attached
charts accessible to `chart_vision`. Add an integration test if not present.

### R5 — Author/channel UX polish

First-class author/channel are in schema. Surface in `/inbox`:
- Autocomplete from `input_authors` table on metadata form
- "Add new author" inline if not found
- Per-author hit-rate badge on each author row (read from `learning/source_attribution`)

(More items added by PM as they surface. Keep iterating; this chat doesn't
"finish" until manual input is genuinely better than the user's previous
trading_agent workflow.)

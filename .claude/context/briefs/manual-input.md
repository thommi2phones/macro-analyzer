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

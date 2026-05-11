# Worker brief: Journal feedback loop

You are a worker chat in the Macro Analyzer project. PM coordinates; you implement inside a declared file territory.

This is a **long-lived chat** — ship v1, then keep iterating as the user closes more trades and patterns emerge.

## Why this exists

`/journal` is currently static — closed trades render passively, no review prompted, the three review fields on `trades` (`was_it_thesis_at_close`, `lesson_at_close`, `hindsight_bias_check`) sit empty because nothing asks for them. We want a **structured review on every trade close** that closes the loop into the scoring engine, source weights, and regime accuracy. The user wants an interactive feedback system, not a write-only diary.

## Orientation (do this first)

Read in order:
1. `.claude/context/STATE.md` — current state
2. `.claude/context/DECISIONS.md` — locked decisions, especially logging contract + fine-tuning-ready (D-2026-05-08-010)
3. `.claude/agents/app/CLAUDE.md` — application-agent conventions
4. `src/macro_positioning/db/schema.py` — `trades`, `trade_reviews` (new, 2026-05-09), `source_outcomes` definitions
5. `src/macro_positioning/learning/source_attribution.py` — what consumes `source_outcomes`; your reviews populate this
6. `src/macro_positioning/learning/score_outcome_correlation.py` — what consumes hindsight calibration
7. `web/journal.jsx` + `web/data.mock.js` (search "closedTrades" / "sourceLeaderboard") — current `/journal` shape
8. `src/macro_positioning/dashboard/desk_data.py` — `build_closed_trades_section`, `build_source_leaderboard_section`

## Scope

End-to-end review flow. Five surfaces:

### A. Schema + status state machine (PM has shipped the schema 2026-05-09)
- `trade_reviews(review_id, trade_id, completed_at, thesis_validity, sources_credited_json, execution_scores_json, setup_score_hindsight, surprise_factor_json, surprise_note, lesson, would_retake, free_form_notes)` — already in `db/schema.py`
- `trades.review_status` column added — values: `closed_pending_review` (just closed, awaiting review), `closed_reviewed` (review done), NULL (legacy)
- On any trade close (manual update or webhook), set `status='closed'` AND `review_status='closed_pending_review'` in the same transaction
- Once a `trade_reviews` row is inserted, flip `review_status='closed_reviewed'`

### B. Backend: review session API
- New package `src/macro_positioning/journal/`
  - `repository.py` — CRUD on `trade_reviews`
  - `feedback_writer.py` — when a review lands, write the derived rows: `source_outcomes` (one per credited source, with attribution_weight), update any aggregates that depend on them
  - `webhook.py` — receiver for tactical-executor close events (`POST /api/integration/trade-close`); triggers the status flip
- New routes in `src/macro_positioning/api/journal_routes.py`:
  - `GET /api/reviews/pending` → list of trades with `review_status='closed_pending_review'` + their context (entry/exit, score-at-entry, source ids that drove them)
  - `POST /api/reviews/{trade_id}` → submit review
  - `GET /api/reviews/recent?limit=20` → for the lessons library
- Mount in `api/main.py`

### C. SPA: pending queue + review modal + lessons library
- `web/journal.jsx` — three new components, in this priority order:
  1. **Pending reviews strip** at the top of `/journal` — visual badge per pending trade, click → opens review modal. Shows count and a gentle "you have 3 reviews waiting" prompt
  2. **Review modal** — the 7-question framework. One screen, scrollable. Submit posts to backend, marks reviewed, refreshes pending list
  3. **Lessons library panel** — scrollable list of past `lesson` entries, searchable by ticker / by tag (e.g., trades where Q1 was `right_outcome_wrong_reason`)
- `web/components.jsx` if you find reusable bits (Likert scale, multi-select chips, etc)

### D. The 7-question framework — DON'T relitigate

Same 7 questions every time. They were designed to:
- Be answerable in <60 seconds total
- Mix structured (for learning) + one short free-text (for memory)
- Distinguish luck-vs-skill, process-vs-thesis failure
- Calibrate the scorer directly via Q4

| # | Question | Field | Shape |
|---|---|---|---|
| Q1 | Was the thesis correct? | `thesis_validity` | enum: `fully_right` / `right_outcome_wrong_reason` / `right_thesis_wrong_outcome` / `fully_wrong` |
| Q2 | Which sources actually drove this trade? | `sources_credited_json` | list[source_id] from registry — multi-select |
| Q3 | Execution quality | `execution_scores_json` | `{entry: 1-5, stop: 1-5, sizing: 1-5, exit: 1-5}` |
| Q4 | Setup score in hindsight | `setup_score_hindsight` | enum: `over` / `right` / `under` |
| Q5 | Surprise factor | `surprise_factor_json` | list[enum]: `macro` / `sector` / `liquidity` / `idiosyncratic` / `none` |
| Q5b | Surprise note | `surprise_note` | optional 1-line free text |
| Q6 | One-line lesson | `lesson` | free text, capped client-side at ~200 chars |
| Q7 | Would you take this trade again? | `would_retake` | enum: `yes` / `no` / `modified` |

(Plus optional `free_form_notes` longer-form field for anyone who wants to write more — not prompted in the modal, only revealed on click of "Add notes".)

### E. Feedback wiring — the loop that makes it not-static

When a review lands (`feedback_writer.py`):

| Review field → | Writes to / triggers |
|---|---|
| Q2 `sources_credited` | One `source_outcomes` row per credited source. `attribution_weight` = 1/N (equal split for now; refine in v2). Carries `outcome_pnl_percent` from `trades.pnl_percent` |
| Q4 `setup_score_hindsight` | Insert into `score_hindsight_overlay` table (PM will add when wiring feedback_writer — for now, ML loop v2's overlay reader probes `data/score_calibration.jsonl` as a stop-gap; do NOT ship the JSONL writer, the table is the locked v1 form). One row per review: `(overlay_id PK, review_id FK, trade_id FK, score_id FK, hindsight_verdict, recorded_at)`. `learning/score_outcome_correlation` reads it to surface "I said 80, hindsight said over" patterns |
| Q5 `surprise_factor` | Aggregated per-regime: a future `regime_instability` indicator on the SPA macro strip reads this |
| Q1 `thesis_validity` | Surfaced in `learning/regime_accuracy` (item 5 in ML loop phase 2 brief) — closes the loop on regime classifier accuracy |

You do NOT need to ship items that aren't wired yet (regime_instability indicator, regime_accuracy consumer). Just produce the data; PM wires display side later.

## File territory (yours to edit)

- `src/macro_positioning/journal/` (new package): `repository.py`, `feedback_writer.py`, `webhook.py`, `__init__.py`
- `src/macro_positioning/api/journal_routes.py` (new) + mount in `api/main.py`
- `src/macro_positioning/cli.py` — add `journal review` subcommand for CLI-driven submission (useful for backfill)
- `web/journal.jsx` — pending strip, review modal, lessons library
- `web/components.jsx` — shared Likert/chips if reusable
- `web/data.mock.js` — add `pendingReviews[]` and `lessonsLibrary[]` mock entries (PM updates `desk_data.py` to populate them after you hand back)
- `tests/macro_positioning/journal/test_*.py`

## Off-limits (escalate to PM)

- `src/macro_positioning/db/schema.py` — `trade_reviews` is shipped; if you need MORE columns, ask
- `src/macro_positioning/dashboard/desk_data.py` — PM wires `pendingReviews` + `lessonsLibrary` into the snapshot after you hand back
- `.claude/context/*` — PM-only

## Done criteria for v1

- Manual flow works: from CLI, mark a trade closed_pending_review, hit `/api/reviews/pending`, submit via `POST /api/reviews/{trade_id}`, see it move to `closed_reviewed`
- SPA flow works: pending trade shows badge on `/journal`, click opens modal, submit closes loop, lessons library shows new entry
- `source_outcomes` rows actually written when Q2 is filled — `learning attribution` CLI shows non-empty results post-review
- Review modal under 60 seconds for a fluent user (your own dogfood test)
- Tests with synthetic fixtures; no dependency on real trades to pass
- `uv run pytest -q` passes (target: 368 + your new tests)
- Webhook receiver returns 200 with valid payload, 422 with invalid; document the payload shape in `docs/integration_with_trading_agent.md`

## Hand-back format

```
SHIPPED: journal feedback loop v1
Branch: claude/<slug>
Commits: <list>
Tests: <count> new
End-to-end demo: <screenshots of pending strip + review modal + lessons library, OR a CLI walkthrough>
Source_outcomes populated: <n rows from your review fixtures>
Webhook contract: <payload shape>
Open questions: <UX decisions PM should ratify>
Refinement candidates spotted: <items for the v2 queue>
```

PM merges, updates STATE.md, wires `pendingReviews` + `lessonsLibrary` into `desk_data.py`. Then this chat keeps iterating per the long-lived rule:

## Refinement queue (v2+)

- **Smart attribution_weight** — instead of 1/N, weight by recency of mention or by `learning/source_attribution` historical hit-rate
- **Re-review prompts** — when a regime shifts, prompt re-review on still-open trades that depended on the old regime
- **Lesson surfacing on new scores** — when a new score matches an old setup pattern, surface relevant past lessons inline in the score reasoning trail
- **Close-loop cron** — auto-prompt for review N hours after close even without webhook
- **Bulk backfill UI** — for the user to retroactively review historical trades
- **Aggregate lessons** — quarterly meta-lesson generation via LLM ("based on 30 reviewed trades, the user's most common failure pattern is X")

## Conventions

- `uv` for everything
- Logging contract for the LLM-touched bits (e.g., aggregate-lessons agent in v2 would write to `agent_call_log`)
- Pure functions where reasonable so PM can wire results into `desk_data.py` cleanly
- Modal closes on submit + on `Esc`; doesn't lose data on accidental close (localStorage draft per trade_id)
- Mobile-responsive: questions stack on narrow viewports, no horizontal scroll on iPhone SE width

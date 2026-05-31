# Worker chat: journal-feedback-loop — checkpoint

_Last updated: 2026-05-10 (v1 SHIPPED, awaiting PM merge + desk_data wiring)_

Worker brief (PM-owned, locked): `.claude/context/briefs/journal-feedback-loop.md`
Approved plan (worker-owned): `~/.claude/plans/you-are-the-journal-feedback-loop-deep-lantern.md`
Worktree: `.claude/worktrees/upbeat-jang-208651/` · Branch: `claude/upbeat-jang-208651`

## Status: v1 ready for handback

Everything in the plan's Done-criteria list is green. Full backend +
CLI + SPA + tests + webhook docs landed. Awaits PM merge and the
`desk_data.py` wiring of `pendingReviews` / `lessonsLibrary` for live
data on the SPA (mock fixtures in `web/data.mock.js` carry it during
dev).

## Done this session

- [x] Plan approved + implemented end-to-end
- [x] `src/macro_positioning/journal/` package — repository, feedback_writer, webhook
- [x] `src/macro_positioning/api/journal_routes.py` (5 routes) + mounted in `api/main.py`
- [x] CLI: `journal {pending,close,review}` subcommands
- [x] 4 test files, 24 new tests (full suite 392 passing, up from 368)
- [x] SPA: `PendingReviewsStrip` (J0) + `ReviewModal` (DrillSheet-wrapped) + `LessonsLibraryPanel` (J6)
- [x] Shared widgets: `<Likert>`, `<EnumPicker>`, `<MultiPicker>` in `web/components.jsx`
- [x] localStorage draft per `review_draft_{trade_id}` — autosave on change, clear on submit
- [x] `web/styles.css` — pending strip, likert/enum/multi pickers, modal form, J6 lessons list, mobile rules
- [x] `web/data.mock.js` — 3 `pendingReviews` + 8 `lessonsLibrary` fixtures
- [x] `docs/integration_with_trading_agent.md` — trade-close webhook contract appended
- [x] Live CLI/API E2E dogfood: seed → webhook close → pending → submit → source_outcomes (2 rows) + calibration jsonl written → recent shows entry

## Known limitations / handback notes

- **Browser visual verification was blocked.** `preview_start` errored
  ("Current directory does not exist") in this worktree env — likely a
  path-with-spaces issue in the Claude Preview MCP. The SPA was verified
  structurally + via live API curl walkthrough. **Recommend Operator pull
  the branch and visually sanity-check `/web/index.html#journal` and
  `iPhone-SE-width` modal before merge.**
- The dynamic `/web/data.js` (served by `dashboard/desk_routes.py`)
  does not yet carry `pendingReviews` / `lessonsLibrary`. PM wires this
  after merge per the brief. Until then the SPA renders empty pending
  strip + empty lessons library against the live API path; flipping
  index.html to load `data.mock.js` (or seeding via the API) shows the
  components live.

## Files Touched This Session (worker territory)

Backend / API / CLI:
- `src/macro_positioning/journal/{__init__,repository,feedback_writer,webhook}.py`
- `src/macro_positioning/api/journal_routes.py` (+ mount in `api/main.py`)
- `src/macro_positioning/cli.py` — `journal {pending,close,review}` subcommands

Tests (24 new, all green):
- `tests/test_journal_repository.py` (6)
- `tests/test_journal_feedback_writer.py` (5)
- `tests/test_journal_webhook.py` (4)
- `tests/test_journal_routes.py` (9) ← new this session

SPA:
- `web/journal.jsx` — `PendingReviewsStrip`, `ReviewModal`, `ReviewSection`, `LessonsLibraryPanel`
- `web/components.jsx` — `Likert`, `EnumPicker`, `MultiPicker`
- `web/data.mock.js` — `pendingReviews[]` (3) + `lessonsLibrary[]` (8)
- `web/styles.css` — appended J0/J6 + modal + picker styles + mobile rules

Docs:
- `docs/integration_with_trading_agent.md` — trade-close webhook section appended

Plan + checkpoint:
- `~/.claude/plans/you-are-the-journal-feedback-loop-deep-lantern.md`
- `.claude/context/workers/journal-feedback-loop-STATE.md` (this file)

NOT touched (PM territory per brief):
- `.claude/context/{STATE,DECISIONS,OPEN-QUESTIONS}.md`
- `src/macro_positioning/db/schema.py` — schema is locked
- `src/macro_positioning/dashboard/desk_data.py` — PM wires after handback

## Open questions for PM

1. **Re-review of an already-reviewed trade?** Modal currently does not
   pre-fill from `get_review` for re-opening; it always starts blank.
   Should it pre-fill, or should re-review be explicitly out-of-scope
   (append-only)?
2. **`pendingReviews.candidateSources` shape** — mock uses display
   names (`"Doomberg"`); PM should clarify whether `desk_data` will
   emit display names or `source_id`s. Modal's MultiPicker currently
   passes whatever is provided as both `value` and `label`; the POST
   body becomes the `sources_credited` list verbatim, which then flows
   into `source_outcomes.source_id`. If `desk_data` will emit ids,
   keep as-is; if display names, we need a name→id mapping on submit.
3. **Modal modality on touch** — DrillSheet is right-anchored at
   90vw on mobile (existing behavior). Should it instead bottom-sheet
   on <640px? (Refinement candidate, not blocking v1.)

## Refinement candidates spotted during dogfood (feed into v2 queue)

- Likert rows for execution (Q3) are vertically tall on mobile; consider
  a compact horizontal mode for that section specifically
- Lessons-library expand toggles per-row but only one row at a time —
  fine for v1, but if user wants to compare two side-by-side, allow
  multi-expand
- POST body validation surfaces all required-section misses one at a
  time; could batch into a checklist banner ("Q1, Q3:sizing, Q6 missing")

## v2 queue (for the long-lived chat) — unchanged

1. Smart `attribution_weight` (recency / hit-rate, not 1/N)
2. Re-review prompt on regime shift for still-open trades
3. Inline lesson surfacing in scoring trail
4. Close-loop cron — auto-prompt N hours after close
5. Bulk backfill UI
6. LLM aggregate meta-lessons quarterly

## Blocked / Waiting

- PM merge + desk_data wiring for live data on the SPA
- Operator visual sanity-check on iPhone-SE-width modal

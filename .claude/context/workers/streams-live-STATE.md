# Worker STATE — streams-live

_Last updated: 2026-06-01_

## Status

SHIPPED on branch `claude/streams-live`. S1 theme map + S2 concepts +
S3 source graph driven by real `signals` + `input_authors` data; mock
in `web/data.mock.js` survives untouched as the empty-DB fallback.

## Scope delivered

- **`src/macro_positioning/dashboard/streams_builders.py`** (NEW, ~330 LOC).
  Pure functions over `sqlite3.Connection`:
  - `build_theme_map(conn)` — extracts themes from `signals.thesis_tags_json`
    + `macro_regime_tags_json` (28d window). Normalizes tags to snake_case,
    title-cases label. Computes `direction` via trust*conviction-weighted
    vote of `signals.side` (LONG/ADD vs SHORT/AVOID; |score|/total > 0.4
    threshold). `lifecycle = 1 - last_7d / max_window`; `novelty = 1 - age/28`;
    `velocity = (tanh((Δ)/max(prev,1)) + 1)/2`. Drops themes with <3 mentions.
  - `build_concepts(conn)` — same theme corpus, pre-filtered to novelty>0.7
    AND velocity>0.4. Synopsis = latest signal's `thesis_summary` truncated
    at last sentence boundary ≤180 chars; falls back to most-recent
    document `cleaned_text` if no thesis_summary. Authors resolved via
    `input_authors.display_name`.
  - `build_source_graph(conn)` — one node per `input_authors` row with
    `last_seen_at` in last 90d (NULL excluded — seeded-but-never-used
    rows aren't active sources). Tier from `trust_weight` thresholds
    (1.4/1.15/0.85/0.5; NULL→2). Weight = clip(trust,0,1.5)/1.5.
    `market_focus` derived from theme tokens + asset_class fallback,
    mapped to the 9 cluster keys in `web/streams.jsx:501`. Links via
    existing `learning.source_attribution.echo_ties(conn)`, filtered to
    pairs whose endpoints exist as nodes.
  - `build_streams_section(conn)` — composes all three. Each child is
    try/except wrapped → empty-safe.

- **`src/macro_positioning/dashboard/desk_data.py`** — wired in:
  `build_streams_section_wrapper()` opens a short-lived sqlite3 connection,
  returns `None` when payload is fully empty (so the `streams` key is
  omitted entirely from the snapshot and `data.mock.js`'s mock streams
  block survives the shallow `Object.assign` merge). Added `_empty_streams`
  fallback and extended `build_desk_snapshot()` loop to honor `None`.

- **`web/streams.jsx`** — added a comment block at the `D.streams` read
  site documenting the API/mock contract. No behavioural change needed:
  when desk_data emits real `streams`, the SPA reads it; when desk_data
  omits the key, the mock survives.

- **`tests/test_streams_builders.py`** (NEW, 13 tests, all pass).
  Covers: tier thresholds, market_focus token vs asset-class precedence,
  title formatting, empty-DB payload, theme noise filter (<3 mentions),
  bullish/mixed direction derivation, tag normalization, concept
  novelty/velocity filter, stale-theme exclusion, source-graph 90d
  window + tier mapping + market_focus token win, echo-tie filtering to
  known nodes. Uses synthetic fixtures via `initialize_database()`.

## Live smoke (against current populated DB)

```
themeMap n= 24
concepts n= 24
sourceGraph nodes n= 176
sourceGraph links n= 0   # no agent_call_log.source_credits or trade_reviews yet
direction breakdown: mixed=22, bullish=2  (~8% non-mixed)
```

## Verification gaps

Browser verification was attempted but the local preview tool errored
out on `getcwd` (sandbox permission issue with `.claude/launch.json`).
The smoke-test against the real DB above proves end-to-end shape; the
SPA was inspected statically and its `D.streams` read path is unchanged
beyond a comment update.

If the next session can run the server, manual checks:
1. Open `/streams`, confirm S1 bubbles are real theme tokens (snake_case
   labels title-cased) not the mock "Uranium / Energy" set.
2. S3: confirm tier-0 nodes (Big_Nuts, joejoe55, Stock Unlocked) ring
   in bright green; flip Big_Nuts' `trust_weight` in DB to 0.4 and
   confirm ring shifts to red on reload.
3. S3 links empty until `agent_call_log.source_credits` or
   `trade_reviews.sources_credited_json` start landing.

## Known limitations / follow-ups

- Synopsis is truncated `thesis_summary` — brief notes this is the v1
  contract, can be upgraded to an LLM summary later without shape change.
- Direction coverage is currently low (~8% non-mixed) because most
  insider-channel signals carry conviction defaults of 1-3 and tags don't
  cleanly align. Once author-calibrated trust_weights propagate and the
  LLM extractor lights up, coverage will rise without code changes.
- `lifecycle` collapses to 0 for themes whose biggest week IS this week
  (intentional per brief: "emerging" sits at left edge). Watch for UI
  bunching at the leftmost axis once data grows.
- Tier thresholds (1.4 / 1.15 / 0.85 / 0.5) are first-pass per brief;
  PM may want to tune after looking at the rendered T0-T4 breakdown.
- `market_focus` token vocab is hard-coded to match
  `web/streams.jsx:501` `_CLUSTERS`; if the JSX cluster list changes,
  update `_CLUSTER_TOKENS` in `streams_builders.py` to match (otherwise
  authors fall through to `"macro"`).

## File territory honored

- Edited only: `dashboard/streams_builders.py` (NEW), `dashboard/desk_data.py`
  (3 small edits: builder, snapshot loop, empty helper), `web/streams.jsx`
  (comment-only swap), `tests/test_streams_builders.py` (NEW), this file.
- Did NOT touch: `web/data.mock.js`, `db/schema.py`,
  `learning/source_attribution.py`, `learning/source_themes.py`,
  `.claude/context/STATE.md`, `.claude/context/DECISIONS.md`.

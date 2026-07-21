# Worker brief: Streams page — make it LIVE (S1 + S2 + S3 full scope)

You are a worker chat in the Macro Analyzer project. PM coordinates; you implement inside declared file territory.

## Why this exists

The `/streams` SPA tab renders three sections (S1 theme map, S2 concepts, S3 source graph) but every value on the page comes from `web/data.mock.js`. **This is the core "themes + streams" vision of the platform.** It must be driven by real data ASAP. The UI is built; the backend wiring is not.

The earlier `streams-redesign` brief delivered the UI and shipped the mock. This brief delivers the backend + the swap from mock → live.

## Orientation (do this first)

Read in order:
1. `.claude/context/STATE.md` — current state, PM/worker model
2. `.claude/context/DECISIONS.md` — MA_DATA contract, logging, fine-tuning-ready
3. `.claude/context/briefs/streams-redesign.md` — the UI contract you're feeding (data shapes for `themeMap[]`, `concepts[]`, `sourceGraph{}`)
4. `web/streams.jsx` — already reads `D.streams.{themeMap,concepts,sourceGraph}`; do not change shapes
5. `web/data.mock.js` line 653 — current mock; you will not delete it, you will make it a fallback
6. `src/macro_positioning/dashboard/desk_data.py` — existing builders pattern (`build_source_health_section`, `build_source_leaderboard_section`); add new builders here
7. `src/macro_positioning/learning/source_attribution.py:639` — `echo_ties()` ALREADY EXISTS. Use it as-is for S3 links
8. `src/macro_positioning/learning/source_themes.py` — `author_themes()`, `trusted_source_themes()`, `author_ticker_drops()` are the theme-extraction primitives
9. `src/macro_positioning/scoring/mention_extractor.py` — `count_mentions()`, `recency_weight()` for theme mention volumes
10. `src/macro_positioning/db/schema.py` lines 363–376, 793–805 — `input_authors` table + later-added `trust_weight`, `category`, `parent_channel` columns
11. `src/macro_positioning/db/schema.py` lines 653–700 — `signals` table; `side` (LONG/SHORT/...) + `thesis_tags_json` + `macro_regime_tags_json` are how you derive theme direction
12. `src/macro_positioning/api/main.py` — wire the new desk_data field into the existing payload

## Scope — three live sections

### S1 — `themeMap[]` (real)

**Source of truth:** `signals` table joined with `learning/source_themes` outputs.

For each theme (extract from `signals.thesis_tags_json` + `signals.macro_regime_tags_json` — tag tokens are the theme IDs; normalize lowercase, snake_case), emit:

```python
{
    "id": "uranium_energy",
    "label": "Uranium / energy",                   # title-case the token; replace "_" with " / "
    "direction": "bullish" | "bearish" | "mixed",  # derived: weighted vote of signals.side among signals tagged with this theme over last 28d
    "lifecycle": 0.0..1.0,                         # 0=emerging, 1=fading. Compute as: 1 - (mentions_last_7d / max(mentions_any_7d_window_in_28d, 1))
    "novelty": 0.0..1.0,                           # 1 - (age_days / 28) clamped to [0,1]
    "velocity": 0.0..1.0,                          # (mentions_last_7d - mentions_prev_7d) / max(mentions_prev_7d, 1), squashed via tanh into [0,1]
    "age_days": int,                               # days since first mention of this theme
    "mentions_by_week": [w-3, w-2, w-1, now],      # length=4, bucketed by extracted_at; recency-weighted is fine, raw count is also fine for v1
    "sources": ["doomberg", "fred", ...],          # distinct source_slug values that contributed mentions in window
}
```

**Direction derivation rule:**
- Pull `signals.side` for all signals where any tag in `thesis_tags_json` or `macro_regime_tags_json` matches theme id, `extracted_at >= now-28d`.
- Weight by `author_trust_weight * conviction`.
- `score = sum(+w for side in {LONG, ADD}) - sum(+w for side in {SHORT, AVOID})`. EXIT/TRIM/HEDGE/WATCH count 0.
- If `|score| / total_weight > 0.4` → "bullish" / "bearish" by sign. Else "mixed".

**Filter:** drop themes with `< 3 total mentions in last 28d`. They're noise.

### S2 — `concepts[]` (real)

Same theme corpus as S1, **filtered to `novelty > 0.7 AND velocity > 0.4`** (the UI re-filters but pre-filter at the API to keep payload small).

```python
{
    "id": "power_grid_bottleneck",
    "title": "Power-grid bottleneck",
    "synopsis": str,           # 1-line, ≤180 chars. v1: take latest signal.thesis_summary among signals tagged with this concept; truncate at last sentence boundary under 180. If thesis_summary is null, fall back to first 180 chars of the source document body. Strip newlines.
    "novelty": 0.0..1.0,
    "velocity": 0.0..1.0,
    "items_count": int,        # distinct signal_ids tagged with this concept in last 14d
    "sources_count": int,      # distinct source_slug values in last 14d
    "source_names": [str, ...],# display names — join through input_authors.display_name; limit 3 (the SPA shows chips)
    "age_days": int,
}
```

**No LLM call required for v1 synopsis.** Truncated thesis_summary is acceptable; the field can be upgraded to an LLM summary later without changing the shape.

### S3 — `sourceGraph{}` (real)

**Nodes** — one per author currently in `input_authors` with `last_seen_at >= now-90d`:

```python
{
    "id": author_id,                               # e.g. "joejoe55"
    "name": display_name,
    "tier": int,                                   # see derivation below
    "weight": float,                               # trust_weight (default 1.0 if NULL); clip to [0, 1.5] then divide by 1.5 → [0..1] for UI scaling
    "market_focus": str,                           # see derivation below
}
```

**Tier derivation** (no schema change — derive in the builder):
- `trust_weight >= 1.4` → tier 0 ("trusted KOL")
- `trust_weight >= 1.15` → tier 1 ("primary, high-weight")
- `trust_weight >= 0.85` → tier 2 ("trusted research")
- `trust_weight >= 0.5`  → tier 3 ("monitored")
- else                    → tier 4 ("noise floor")
- NULL `trust_weight` → tier 2 (baseline assumption).

**market_focus derivation** (no schema change — derive):
- Pull all `signals` for this `author_id` in last 90d.
- Aggregate `signals.asset_class` + tokens from `thesis_tags_json`.
- Map to the cluster keys defined in `web/streams.jsx:501` (`macro`, `equities`, `tech`, `energy`, `realassets`, `crypto`, `credit`, `fx`, `social`). The mapping function lives in the builder; keep it simple and pure.
- If author has zero signals: default to `"macro"` (the leftmost cluster — least visually disruptive).

**Links** — call `learning.source_attribution.echo_ties(conn)` (already exists at line 639) and map to:

```python
{"source": pair["source_a"], "target": pair["source_b"], "strength": pair["strength"]}
```

Filter to pairs where both endpoints exist in the nodes list above.

### Backend deliverables

1. **New module: `src/macro_positioning/dashboard/streams_builders.py`** — keep `desk_data.py` from bloating further. Public functions:
   - `build_theme_map(conn) -> list[dict]`
   - `build_concepts(conn) -> list[dict]`
   - `build_source_graph(conn) -> dict`
   - `build_streams_section(conn) -> dict` returning `{themeMap, concepts, sourceGraph}`
2. **Wire into `desk_data.py`** — `build_desk_snapshot()` calls `build_streams_section()` and adds it to the output dict under `streams`.
3. **API**: `/api/desk` already returns the snapshot; verify the new field flows through. No new endpoint required unless `/api/streams` makes sense as a lazy-load (PM is fine either way — pick whichever keeps initial page weight reasonable; if streams payload > 50KB lazy-load it).
4. **SPA swap**: in `web/streams.jsx:868`, change the source of `s` from `D.streams` to the API payload. Keep `data.mock.js` `streams: {...}` block as fallback when the API returns null/empty, so dev-mode without a DB still renders something.

### Empty-data behavior

Every builder MUST return a sensible empty payload (empty list / empty graph) when the DB has insufficient data. The SPA already handles empty states. Do not raise.

## File territory (yours to edit)

- `src/macro_positioning/dashboard/streams_builders.py` — NEW
- `src/macro_positioning/dashboard/desk_data.py` — call site only (one import + one line in `build_desk_snapshot`)
- `web/streams.jsx` — swap mock → API payload (line ~868), preserve fallback
- `tests/test_streams_builders.py` — NEW; synthetic fixtures for each builder + empty-data path
- `.claude/context/workers/streams-live-STATE.md` — your worker handoff log

## Off-limits (escalate to PM)

- `web/data.mock.js` — read-only (keep the mock for fallback)
- `src/macro_positioning/db/schema.py` — no new columns or tables for v1; everything derives in-builder
- `src/macro_positioning/learning/source_attribution.py` — `echo_ties()` stays as-is; if you need to extend it, escalate
- `src/macro_positioning/learning/source_themes.py` — consume its public functions; do not modify
- `.claude/context/STATE.md`, `.claude/context/DECISIONS.md` — PM owns
- `web/app.jsx`, `web/components.jsx`, other section builders in `desk_data.py`

## Done criteria

- `uv run python -c "from macro_positioning.dashboard.streams_builders import build_streams_section; from macro_positioning.db.schema import connect; print(build_streams_section(connect()))"` returns a dict with `themeMap`, `concepts`, `sourceGraph` keys.
- With a populated DB, `themeMap` has ≥1 entry, `sourceGraph.nodes` matches the count of recently-active authors, `sourceGraph.links` is non-empty iff `echo_ties` finds any.
- With an empty DB, all three are empty lists/dicts and no exception is raised.
- SPA `/streams` tab renders the same UI but values originate from the API (verify via DevTools network panel + by editing an author's trust_weight in DB and seeing the tier ring color change).
- `uv run pytest -q tests/test_streams_builders.py` passes; full suite stays at or below current pass count.
- Direction field is populated (not 100% "mixed") when ≥1 theme has aligned signal sides.

## Verification (use the run skill)

After implementation, run the app and screenshot `/streams`. The check: pick one tier-1 author known to have signals (e.g. Doomberg, Forward Guidance), confirm its node appears in S3 with the expected ring color, and confirm at least one theme it touches appears in S1.

## Hand-back format

Write `.claude/context/workers/streams-live-STATE.md` and respond with:

```
SHIPPED: Streams live (S1 theme map + S2 concepts + S3 source graph)
Branch: claude/<slug>
Commits: <list>
Tests: <count> new
Counts: themeMap=<n>, concepts=<n>, graph nodes=<n>, links=<n>
Direction coverage: <% of themeMap with non-"mixed" direction>
Open questions: <UX decisions PM should ratify>
Follow-ups: <known limitations — e.g. LLM synopsis upgrade, tier thresholds tuning>
```

## Conventions

- `uv` for everything
- No new external deps (the theme math is all stdlib + sqlite)
- Pure functions in `streams_builders.py` so `desk_data.py` can call them with any connection
- Empty-data paths must not crash
- Match existing builder patterns in `desk_data.py` (return JSON-serializable dicts, no datetime objects in payload — use ISO strings)

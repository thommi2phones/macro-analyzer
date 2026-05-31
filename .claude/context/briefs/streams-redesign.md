# Worker brief: Streams page redesign (S1 theme map · S2 concepts · S3 source graph)

You are a worker chat in the Macro Analyzer project. PM coordinates; you implement inside declared file territory.

## Why this exists

The `/streams` page currently has two sections: a grid of theme cards (S1) and a per-source feed (S2). A design session produced a richer three-section layout that the user has approved:

- **S1** — Animated theme scatter map (EMERGING→FADING × BULLISH→BEARISH) with a PLAY/scrub timeline
- **S2** — Emerging concepts cards (novelty + velocity scored, replaces the theme-card grid)
- **S3** — Source network graph: force-directed SVG where bubble = source, ring = tier (T1–T4), thread = echo tie (co-citation strength)

PM has already shipped Track A (text search + DrillSheet drilldown on the existing S2 per-source feed) in commit `ba90eb7`. That per-source feed stays but is now section **S4** — the new S2 and S3 sit above it.

## Orientation (do this first)

Read in order:
1. `.claude/context/STATE.md` — current state
2. `.claude/context/DECISIONS.md` — MA_DATA contract, logging, fine-tuning-ready
3. `web/streams.jsx` — current file (S1 cards, S4 per-source feed); you will extend this
4. `web/data.mock.js` — `streams.*` shape; you must add `themeMap[]`, `concepts[]`, `sourceGraph{}` to the mock
5. `web/components.jsx` — reuse `DrillSheet` + `SourceDetailPanel` for S3 drilldown
6. `src/macro_positioning/dashboard/desk_data.py` — look at `build_source_health_section()` for the pattern; PM will add the new builders after hand-back (you just define the schema + add mock data)
7. `src/macro_positioning/learning/source_attribution.py` — `attribution_30d()` for reference; you'll add `echo_ties(conn)` here
8. `web/styles.css` — existing patterns; mirror them

## Scope

### S1 — Theme map (animated scatter)

**What it shows:** Each bubble is a narrative theme. X-axis = lifecycle (EMERGING on left, FADING on right), Y-axis = direction (BULLISH top, BEARISH bottom, MIXED middle). Bubble size = mention volume. Gold dashed ring = emerging (age < 14d). Faint drift trails trace path over time.

**Time-lapse:** A scrubber/PLAY control at top sweeps through the last 4 weeks. At each tick, bubble positions and sizes change to reflect that moment's data. At NOW, source-overlap threads appear (lines connecting themes that share a source).

**Data shape to add to `D.streams.themeMap[]`:**
```js
{
  id: "uranium_energy",          // stable ID
  label: "Uranium / energy",
  direction: "bullish",          // "bullish" | "bearish" | "mixed"
  lifecycle: 0.72,               // 0=emerging, 1=fading
  novelty: 0.84,
  velocity: 0.74,
  age_days: 28,
  mentions_by_week: [4, 7, 11, 14],  // oldest→newest, length=4 (4 weeks)
  sources: ["doomberg", "energy_capitalist", "capitalist_exploits"],
}
```

**Implementation notes:**
- SVG element, no external charting library (inline React SVG)
- Bubble x = `lifecycle * svgWidth`, y = direction mapped to band (bullish=top 33%, mixed=middle, bearish=bottom 33%) + small random jitter seeded by theme id
- Bubble r = scaled from mentions at current week tick (3–20px range)
- Animation: `requestAnimationFrame` scrubber, OR simpler: slider `<input type="range">` that controls `weekIndex` state (0=4w ago, 3=now)
- Gold dashed ring: render when `age_days < 14` at current tick
- Drift trails: SVG `<polyline>` connecting the bubble's positions across all 4 ticks
- Source-overlap threads: thin lines between themes that share a source — only render when `weekIndex === 3` (NOW)
- Play button: setInterval over weekIndex 0→3, 800ms per step; pauses at 3
- Empty-state: if `themeMap.length === 0`, show "no recurring themes mapped yet" in the SVG area

### S2 — Emerging concepts cards

**What it shows:** High-novelty, high-velocity theme cards. Each card = one concept. Shows: title/label, synopsis (1-2 lines), novelty score, velocity, items count, sources count, source name chips, age.

**Data shape to add to `D.streams.concepts[]`:**
```js
{
  id: "power_grid_bottleneck",
  title: "Power-grid bottleneck",
  synopsis: "ERCOT capacity headlines + transformer lead-time stretching to 220wks. Crosses uranium + AI-capex.",
  novelty: 0.84,
  velocity: 0.74,
  items_count: 4,
  sources_count: 3,
  source_names: ["Kalecki Note", "Doomberg", "Reuters"],
  age_days: 6,
}
```

**Filter:** Only show items where `novelty > 0.7 AND velocity > 0.4`. Show the filter criteria in the block subtitle.

**Empty-state:** "no high-novelty themes this week"

### S3 — Source network graph

**What it shows:** Force-directed SVG graph. Each node is a source. Node size = trust_weight × base_radius. Ring color/width = tier (T1=gold thick, T2=green medium, T3=amber thin, T4=muted dashed). Threads between nodes = echo ties (co-citation strength, 0..1). Thread opacity = strength. Hover a node → highlight its echo ties, show a tooltip with name + weight. Click a node → open `SourceDetailPanel` DrillSheet (already built in `web/components.jsx`).

**Data shape to add to `D.streams.sourceGraph{}`:**
```js
{
  nodes: [
    { id: "doomberg", name: "Doomberg", tier: 1, weight: 0.92, market_focus: "energy" },
    { id: "fred", name: "FRED", tier: 1, weight: 0.78, market_focus: "macro" },
    // ...one per active source
  ],
  links: [
    { source: "doomberg", target: "energy_capitalist", strength: 0.82 },
    { source: "fred", target: "bianco_research", strength: 0.61 },
    // ...echo ties with strength > 0.3
  ],
}
```

**Tier → visual mapping:**
- T1: gold (`#d6b15a`) ring, r = weight × 28
- T2: green (`#50b478`) ring, r = weight × 22
- T3: amber (`#e0a030`) ring, r = weight × 18
- T4: muted (`#666`) dashed ring, r = weight × 14

**Implementation notes:**
- Simple spring simulation with 1 iteration of force layout on mount (no D3 needed — use a small custom hook or static positions from config)
- OR: assign static positions grouped by market_focus cluster (macro cluster left, energy cluster right, news/social bottom) — simpler and more predictable
- Thread = SVG `<line>` with `opacity = strength`, `strokeWidth = strength * 2`
- Hover: set `hoveredNode` state, dim all non-adjacent threads
- Click: set `openSrc` state → `<DrillSheet>` (same pattern as Track A)
- Empty-state: if `sourceGraph.nodes.length === 0`, show "no sources connected yet"

### Backend: `echo_ties(conn)` function

Add to `src/macro_positioning/learning/source_attribution.py`:

```python
def echo_ties(conn: sqlite3.Connection) -> list[dict]:
    """Co-citation strength between source pairs.

    Two sources are co-cited when they both appear in source_credits of the
    same agent_call_log entry, OR both credited in the same trade_review's
    sources_credited_json.

    Returns list of {source_a, source_b, strength} where strength is the
    normalized co-occurrence count (0..1, divided by max pair count).
    Filters out pairs with strength < 0.1.
    Empty list if insufficient data.
    """
```

**Data sources to query:**
- `source_outcomes` table: group by `trade_id`, collect sources → count pair co-occurrences
- `trade_reviews.sources_credited_json`: parse JSON list → count pair co-occurrences
- Combine both counts, normalize by max, filter strength < 0.1

### Updated section numbering in `web/streams.jsx`

| Block num | Section |
|---|---|
| S1 | Theme map (animated scatter) — NEW |
| S2 | Emerging concepts — NEW |
| S3 | Source network graph — NEW |
| S4 | Per-source feed (was S2) — existing, keep as-is |

## File territory (yours to edit)

- `web/streams.jsx` — extend with S1, S2, S3 sections; renumber old S2→S4
- `web/data.mock.js` — add `D.streams.themeMap[]`, `D.streams.concepts[]`, `D.streams.sourceGraph{}` with ≥3 mock entries each
- `web/styles.css` — add styles for `.theme-map`, `.concept-card`, `.source-graph`, `.sg-node`, `.sg-link`, `.sg-tooltip`
- `src/macro_positioning/learning/source_attribution.py` — add `echo_ties(conn)` function
- `tests/test_learning_source_attribution.py` (or new `tests/test_echo_ties.py`) — add tests for `echo_ties()` with synthetic fixtures

## Off-limits (escalate to PM)

- `src/macro_positioning/dashboard/desk_data.py` — PM adds the new section builders after hand-back
- `src/macro_positioning/db/schema.py` — no new tables needed
- `.claude/context/*`
- `web/app.jsx`, `web/components.jsx` — read-only (DrillSheet + SourceDetailPanel already exported)

## Done criteria

- S1: PLAY button animates through 4 weeks; scrubber works; bubbles move; drift trails visible; gold ring shows/hides; source threads appear at NOW
- S1 empty-state: renders static placeholder when `themeMap = []`
- S2: Concepts cards render from `D.streams.concepts`; novelty > 0.7 + velocity > 0.4 filter applied; empty-state works
- S3: Source graph renders nodes with tier rings; threads drawn proportional to strength; hover highlights echo ties; click → DrillSheet with SourceDetailPanel
- S4: Existing per-source feed still works (search + sort + drilldown from Track A)
- `echo_ties()` returns empty list gracefully when no data; tests pass with synthetic fixtures
- `uv run pytest -q` passes (baseline: 419 passed, 1 pre-existing failure in test_watchlist_resolver)

## Hand-back format

```
SHIPPED: Streams redesign (S1 theme map + S2 concepts + S3 source graph)
Branch: claude/<slug>
Commits: <list>
Tests: <count> new
Demo: <screenshots or description of S1 animation, S2 cards, S3 graph>
Mock data: <count of themeMap / concepts / sourceGraph nodes+links entries>
echo_ties schema: <describe what the function returns>
Open questions: <any UX decisions PM should ratify>
```

## Design reference

The approved design shows (from screenshot):
- S1: Dark scatter plot, gold "EMERGING" label on x-axis left, "FADING" right; "BULLISH" top, "BEARISH" bottom. Bubbles have gold dashed rings for emerging themes. Faint dotted legend top-right.
- S2: Three-column card layout, one card per concept. Each shows NEW badge + age, NOVELTY score, title, 1-line synopsis, velocity/items/sources counts, source name chips.
- S3: Network graph with dark background. Node labels show tier (T1/T2/T3/T4) + weight. Nodes grouped by market_focus cluster (macro-rates cluster left, energy-commodities cluster right, news-social bottom). Legend top-right showing T1–T4 colors + thread = co-citation.

## Conventions

- `uv` for everything
- No external charting libraries (inline SVG only)
- Pure functions where possible so PM can wire into desk_data.py
- Empty-data paths must not crash
- Match existing color variables from styles.css: `var(--accent)` = gold, `var(--green)`, `var(--border)`, `var(--bg2)`, `var(--mono)`, `var(--serif)`

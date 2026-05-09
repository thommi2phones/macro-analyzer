# Inputs Pipeline — Workstream ①

**Owner:** Application Agent (with Thesis Agent input on source quality assessment)
**Status:** spec — implementation begins Phase 3 of the project plan
**Related configs:** `config/sources.json`, `config/source_routing.json`
**Related code (existing, to be extended):** `src/macro_positioning/ingestion/`, `src/macro_positioning/db/`

---

## Purpose

A disciplined, observable, self-improving pipeline of data into the brain. Every source has an owner, a weight, a freshness SLA, and an outcome attribution loop. This is workstream ① of four — **without it, the brain is reading garbage**.

---

## Source taxonomy (current state)

19 sources canonically registered in `config/sources.json`:

| Type | Count | Examples |
|---|---|---|
| Newsletters (Substack/Gmail) | 10 | MacroMicro, Doomberg, Kaoboy Musings, Real Vision, Stock Unlocked, QTR, Bitcoin Layer, DeepValue, Blockworks Breakdown, Weekly Wizdom |
| Podcasts | 4 | Forward Guidance, Wolf of All Streets, Real Vision Journey Man (all transcribed); Moonshots (show notes only) |
| API time-series | 1 | FRED (60+ economic series) |
| API news+sentiment | 1 | Finnhub |
| RSS broad headlines | 1 | Google News (macro topic queries) |
| Manual | 2 | User notes via CLI; chart screenshots via dashboard upload |

12 core / 7 secondary by current trust weight.

---

## Source lifecycle (9 stages)

### 1. Discovery
- Gmail scan for new newsletter subscriptions (`personal_gmail.py` already does this)
- Podcast network sitemap crawl (Blockworks alone has 137 candidates — curate, don't backfill all)
- Manual add via CLI when user hears about a new analyst
- Future: monitor Twitter/X follows for emerging KOLs

### 2. Onboarding
Add to `config/sources.json` with:
- `source_id` (snake_case unique)
- `source_type`, `priority` (start as `trial`)
- `trust_weight` (start at 0.5)
- `routing_tags` (which agents care — see `source_routing.json`)
- `fetch_cadence` (ISO-8601 duration)
- `freshness_sla_hours` (when content goes stale)
- `validation_focus` (which framework regimes this source is most credible on)
- `channels` (one or more fetch endpoints)
- `onboarded_at` (today's date)

After 30 days at `trial`, promote to `secondary` if active and contributing, else archive.

### 3. Normalization
Per-source connector → `Document` model (existing `core/models.py`). Handles:
- HTML stripping (existing `BeautifulSoup` flow)
- Encoding normalization
- RFC-2822 / ISO date parsing
- Title extraction
- Author resolution
- URL canonicalization

### 4. Dedup
Existing unique constraint on `(source_id, url)` in documents table. Re-run safety verified by `tests/test_repository_dedup.py` (5/5 passing).

### 5. Pre-tagging
Lightweight keyword routing (no LLM cost). Tags decide which agents wake up:
- `inflation`, `rates`, `fed`, `liquidity` → `regime_classifier`
- `crypto`, `equities`, `commodities`, `energy` → `narrative_synthesizer` + `sector_theme_scorer`
- `chart` → `chart_vision` + `technical_scorer`
- See `config/source_routing.json` for full tag → agent map

If a document matches zero routing tags after pre-tagging → log as skipped, surface in source health panel. Don't burn LLM calls on irrelevant content.

### 6. Freshness scoring
Decay function on `published_at`:
```
freshness = max(0, 1 - (now - published_at) / freshness_sla_hours)
```
A weekly newsletter (SLA 168h) is fully fresh at publish, 50% at day 3.5, expired at day 7.
Stale documents get downweighted in synthesis but not deleted. Useful for "here's what was being said when this trade went on."

### 7. Outcome attribution
When a trade closes, attribute outcome to contributing sources:
- `source_outcomes` table (added in this phase) records: `source_id`, `trade_id`, `attribution_weight`, `outcome_pnl`, `contribution_type`
- `attribution_weight` is the fraction of the brain's score that came from this source's documents
- `contribution_type` is one of: `regime_call`, `thesis_alignment`, `theme_strength`, `risk_flag`, `entry_timing`

Worked example: trade in URNM closes +12%. Brain's score at entry was 82, with `sector_theme_strength` 8/10 driven 60% by Doomberg's recent energy-security commentary, 30% by Kaoboy, 10% by FRED uranium price series. → Doomberg gets attribution_weight 0.6 × 12% = 7.2pp; Kaoboy gets 3.6pp; FRED gets 1.2pp. These accumulate into source weight nudges.

### 8. Fine-tuning per source
Some sources have distinctive rhetorical styles that benefit from tailored extraction prompts. Examples:
- Doomberg's contrarian framing inverts surface meaning → custom prompt for negation
- Forward Guidance episodes are 90+ minutes → chunked summarization with overlap
- Bitcoin Layer mixes pure macro and BTC-specific commentary → routing branch within source

Per-source overrides live in a future `config/source_prompts.json` (not built yet — defer until evidence shows we need it).

### 9. Offboarding
Sources with sustained negative attribution (≥30 days, attribution score < -0.2) → archive (set `archived_at`, don't delete). Don't fetch new content but keep historical data for re-evaluation.

---

## CLI surface (Phase 3)

```
macro-positioning sources list
    → table: source_id | priority | trust_weight | last_fetched | freshness | 30d_attribution | routing_tags

macro-positioning sources add <source_id> --type newsletter --url <url> --tags macro,rates
    → adds to sources.json with default trust_weight 0.5, priority trial, triggers immediate fetch

macro-positioning sources archive <source_id>
    → sets archived_at, stops fetches

macro-positioning sources promote <source_id> --to core
    → bumps priority

macro-positioning sources retag <source_id> --add liquidity --remove fx
    → updates routing_tags
```

---

## Files

```
config/
  sources.json                       # canonical registry (DONE this phase)
  source_routing.json                # tag → agent map (DONE this phase)
  source_prompts.json                # per-source extraction overrides (FUTURE, when needed)

src/macro_positioning/ingestion/
  source_lifecycle.py                # NEW Phase 3: add/promote/archive/discover
  pre_tagger.py                      # NEW Phase 3: keyword routing
  freshness.py                       # NEW Phase 3: decay + scoring

src/macro_positioning/db/
  source_outcomes table              # DONE this phase (in schema.py)
```

---

## Verification

- `python -m macro_positioning.cli sources list` shows all 19 sources with weight/freshness/attribution
- `python -m macro_positioning.cli sources add test_source --type newsletter --url ...` creates entry, triggers fetch within 1 minute
- Closed trade in DB triggers per-source weight update visible in `/dev` source health panel
- All routing tags in `config/sources.json` exist in `config/source_routing.json` (CI check)

---

## Anti-patterns to avoid

- **Backfilling everything** — Blockworks has 137 podcasts in their sitemap. We don't need them all. Curate to top 5-10.
- **Equal-weight new sources** — start every new source at trust_weight 0.5 regardless of how exciting it sounds. Earn the weight.
- **LLM calls before pre-tagging** — pre-tagger is keyword-only by design. Don't sneak an LLM in.
- **Deleting archived sources** — they're useful for "what would the system have said with v3 source weights" backtests.
- **Per-source code in connectors** — if a source needs special handling, it goes in `source_prompts.json`, not in `if source_id == 'doomberg'` branches.

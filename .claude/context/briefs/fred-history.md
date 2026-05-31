# Worker brief: FRED historical persistence

You are a worker chat in the Macro Analyzer project. PM coordinates; you implement inside a declared file territory.

## Why this matters

Today the FRED provider only fetches the latest observation per series and never writes to SQLite. Every consumer that needs *change-over-time* — `liquidity_alignment` (NFCI 4w change), regime persistence checks, the future ML learning loop, retroactive backtesting — has no data to work with. Score outputs are effectively snapshot-only. This worker installs the historical-persistence layer so every downstream classifier and scorer can operate on a real time series.

## Orientation (do this first)

Read in order:
1. `.claude/context/STATE.md` — current shipped state
2. `.claude/context/DECISIONS.md` — locked architectural decisions
3. `src/macro_positioning/market/fred_provider.py` — current latest-only fetcher; series catalog (~52 series)
4. `src/macro_positioning/market/macro_indicators.py` — `compute_fci`, quadrant, EPU classifiers (will become consumers of the new history table)
5. `src/macro_positioning/db/schema.py` — schema; you may add the new table here per protocol
6. `src/macro_positioning/dashboard/desk_data.py` — current FCI consumer (live-fetch with 1h cache); will be refactored to read from SQLite
7. `src/macro_brain/agents/liquidity_alignment/scorer.py` — already expects `nfci_4w_change`; today receives None
8. `src/macro_positioning/scoring/runner.py` — preloads liquidity_features per pass; will be wired to read history

## Scope

Build the historical-persistence layer for FRED. NOT:
- a generic time-series cache
- a paid API integration
- a backfill of intraday/high-frequency data (FRED is daily/weekly/monthly; that's fine)

DO:
- One new table: `fred_observations` (append-only, idempotent on re-fetch)
- One backfill CLI: `macro-positioning fred backfill [--series ID] [--start YYYY-MM-DD]`
  - Default: maximum available history per series. Many FRED series predate 2000 (NFCI from 1971, CPI from 1947, etc.). Pass `observation_start=1900-01-01` to FRED — the API returns whatever exists. Storage is trivial (~52 series × mostly weekly/monthly cadence ≈ <50MB SQLite).
- Incremental fetcher invoked **on every `score run`** (cheap latest-only delta — last 7 days per series, idempotent upsert). No separate cron yet; the score-run hook is the refresh loop.
- Read helpers: `latest_value(series_id)`, `value_at_or_before(series_id, date)`, `change_over(series_id, days)`, `series_at_date(series_id, date)` (for regime trajectory)
- Refactor `compute_fci()` to **DB-first, live-fallback**: accepts an optional SQLite connection; when present, reads from `fred_observations`; only falls back to live FRED HTTP when DB is empty/stale. Existing call sites stay working.
- Wire **all three** time-series consumers in this PR:
  1. `liquidity_alignment` — real `nfci_4w_change` from DB
  2. `compute_fci()` — DB-first refactor (also benefits `desk_data.py` dashboard strip; latency drops from FRED-HTTP to local SQLite read)
  3. Regime trajectory — extend `classify_growth_inflation_quadrant()` to optionally accept a 4-week-ago snapshot so the quadrant classifier sees direction, not just level. Surface trajectory deltas in the FCIResult-style return where useful.
- Tests covering: backfill idempotency, incremental upsert, `change_over` math, FCI from DB matches FCI from live obs (parity test), liquidity_alignment with real history, regime trajectory direction sanity

## File territory (yours to edit)

- `src/macro_positioning/db/schema.py` — add `fred_observations` table + indexes (this brief explicitly authorizes the schema change)
- `src/macro_positioning/market/fred_history.py` (new) — fetcher + writer + read helpers
- `src/macro_positioning/market/fred_provider.py` — extend with `fetch_history()` method; do NOT remove the existing `gather()` path
- `src/macro_positioning/market/macro_indicators.py` — `compute_fci(observations=None, conn=None)` — add the conn-aware path
- `src/macro_positioning/cli.py` — add `fred backfill` and `fred refresh` subcommands
- `src/macro_positioning/scoring/runner.py` — replace the current `liquidity_payload = {... "source": "missing"}` with a real read from the new helpers
- `src/macro_positioning/dashboard/desk_data.py` — `_build_macro_indicators` reads from DB first; live FRED only on cold-cache fallback
- `tests/test_fred_history.py` (new), `tests/test_macro_indicators_from_db.py` (new), extend `tests/test_brain_liquidity_alignment.py`

## Off-limits (escalate to PM)

- `web/` — frontend
- `desk_data.py` SPA contract field names — you may swap data sources, but the keys returned in `_build_macro_indicators` must stay identical
- `.claude/context/*` — STATE/DECISIONS/OPEN-QUESTIONS are PM-owned

## Schema sketch

```sql
CREATE TABLE fred_observations (
    series_id           TEXT NOT NULL,
    observation_date    TEXT NOT NULL,   -- ISO YYYY-MM-DD
    value               REAL NOT NULL,
    realtime_start      TEXT,            -- FRED vintage start (revisions)
    realtime_end        TEXT,            -- FRED vintage end
    fetched_at          TEXT NOT NULL,   -- ISO 8601 UTC
    PRIMARY KEY (series_id, observation_date, realtime_end)
);
CREATE INDEX idx_fred_obs_series_date
    ON fred_observations (series_id, observation_date DESC);
```

`realtime_*` columns capture FRED revision vintages so we can replay "what did we know on date X" — non-trivial for retroactive backtesting. PK on `(series_id, date, realtime_end)` makes re-fetch idempotent and revision-aware.

## Done criteria

- All ~52 catalogued FRED series backfilled to maximum available history (FRED returns whatever exists from 1900-01-01)
- `score run` invokes the incremental refresh (last 7d per series, idempotent) before scoring
- `liquidity_alignment` reads NFCI history from SQLite and shows real spread (not 8/8/8)
- `compute_fci()` is DB-first; parity test confirms DB-derived FCI matches live-derived FCI within float tolerance
- `desk_data._build_macro_indicators` reads from DB; live HTTP only on cold-cache fallback
- `classify_growth_inflation_quadrant()` accepts optional 4-week-ago snapshot and exposes a direction signal in its return type
- `uv run pytest -q` passes; ≥15 new tests
- Backfill is idempotent: running twice doesn't duplicate rows (PK + upsert)
- A clear log line when a consumer falls back to neutral because a required series is missing

## Hand-back format

```
SHIPPED: FRED historical persistence
Branch: claude/<slug>
Commits: <list>
Tests: <count> new, <count> total
Backfill: <total rows>, NFCI earliest/latest, total series populated / total catalogued
liquidity_score spread before/after: <numbers>
FCI parity test: max abs diff vs live = <number>
Regime trajectory: sample 4w direction reads (e.g. "growth: -0.3, inflation: +0.1")
Open questions: <if any>
```

## Conventions

- `uv` for everything. Never `pip`.
- Reads/writes go through repository pattern where possible
- Keep WAL mode enabled — long backfills must not block readers
- Failed series fetches log + skip; don't crash the backfill

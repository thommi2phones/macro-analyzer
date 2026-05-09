# Worker brief: ML / learning loop

You are a worker chat in the Macro Analyzer project. PM coordinates; you implement inside a declared file territory.

## Orientation (do this first)

Read in order:
1. `.claude/context/STATE.md` — see "Next Steps — ML / Learning Loop" section, the 7 items there are your scope
2. `.claude/context/DECISIONS.md` — note especially D-2026-05-08-010 ("fine-tuning-ready from day one") and `docs/logging_contract.md`
3. `.claude/agents/app/CLAUDE.md` — application-agent conventions
4. `src/macro_positioning/db/schema.py` — read the `agent_call_log`, `source_outcomes`, `trade_scores` table definitions; these are your data sources
5. `docs/logging_contract.md` — the contract every LLM call satisfies; you read its outputs

## Scope

Build the read/analytics side of the data flywheel. Tables already collect data; nothing consumes them yet. Your job: turn raw rows into surface-able signal.

**Priority order (smallest first move first):**

1. **Source attribution aggregator** — query `source_outcomes` → per-source 30/90d net P&L attribution. Surface in `sourceLeaderboard` on `/journal` (currently empty array in `desk_data.py`).
2. **Score → outcome correlation** — Spearman ρ between `adjusted_total_score` at entry and `pnl_percent` at close. Per sub-component too. Surface in `/dev` cost/quality panel.
3. **Mention extraction precision** — when a ticker auto-promotes via mentions, does it later score well / produce a trade? Compute precision@k.
4. **Per-call quality scoring** — add `quality_score` column to `agent_call_log` (PM does the schema change). Heuristic: was the output downstream-confirmed? Backfill historical rows.
5. **Regime classifier accuracy** — backtest harness. When classifier said "X" in month M, did M+1/M+2 behave like X? Monthly rollup.
6. **Retraining triggers** — config + threshold logic for when to kick first trained models. Output a `should_retrain` flag, don't actually retrain.
7. **Model versioning** — add `model_version` column to `agent_call_log` (PM schema change). Wire writers to populate it.

Stop after item 3 and hand back; PM evaluates whether to continue or branch.

## File territory (yours to edit)

- `src/macro_positioning/learning/` (new package)
  - `__init__.py`
  - `source_attribution.py`
  - `score_outcome_correlation.py`
  - `mention_precision.py`
  - `quality_scorer.py`
  - `retraining_triggers.py`
- `tests/macro_positioning/learning/test_*.py`
- `src/macro_positioning/cli.py` — add `learning` subcommand group (e.g. `learning attribution`, `learning correlation`)

## Off-limits (escalate to PM)

- `src/macro_positioning/db/schema.py` — items 4, 7 need columns; ASK, don't add
- `src/macro_positioning/dashboard/desk_data.py` — surfacing into the SPA is a PM step. You produce the data; PM wires it.
- `web/` — frontend
- `.claude/context/*`
- `src/macro_brain/` — that's the heuristic-scorers and llm-agents chats

## Done criteria

- Each module is a queryable function: `def attribution_30d(conn) -> list[dict]`, etc.
- CLI commands print results so they're inspectable without the dashboard
- `uv run pytest -q` passes; each module has fixtures with synthetic `source_outcomes` / `trade_scores` rows
- Empty-data case returns empty list / `None`, never crashes
- Hand back BEFORE wiring anything into `desk_data.py` — that's PM's job

## Hand-back format

```
SHIPPED: ML learning loop (items 1-3)
Branch: claude/<slug>
Commits: <list>
Tests: <count> new
Sample output: <paste output of `uv run python -m macro_positioning.cli learning attribution`>
Schema requests: <if any — describe column needs for items 4/7 if you got there>
Open questions: <ambiguity in source_outcomes population, etc>
```

## Conventions

- `uv` for everything
- Pure functions taking `conn` so PM can wire into `desk_data.py` without surprises
- No LLM calls — this is analytics on existing data
- If `source_outcomes` is empty (no closed trades yet), return empty result with a clear log; don't error

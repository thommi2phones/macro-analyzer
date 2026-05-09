# Worker brief: ML learning loop items 4–7

You are a worker chat in the Macro Analyzer project. PM coordinates; you implement inside a declared file territory.

> **Prerequisite:** items 1–3 already shipped (`85e186a`). PM has just added the schema columns this brief needs (`cc9431a`): `agent_call_log.call_type`, `agent_call_log.quality_score`, `agent_call_log.model_version`. Pull main before starting.

## Orientation (do this first)

Read in order:
1. `.claude/context/STATE.md` — see "ML / Learning Loop" + "Open scope"; items 4–7 listed there
2. `.claude/context/DECISIONS.md` — D-2026-05-08-010 (fine-tuning ready) is the north star
3. `src/macro_positioning/learning/` — your existing modules (items 1–3); mirror their shape
4. `src/macro_positioning/db/schema.py` — `agent_call_log` definition + the just-added columns
5. `docs/logging_contract.md` — the contract LLM agents satisfy; you read its outputs

## Scope

Items 4–7 from the original brief. Schema unblocked.

### 4. Per-call quality scoring
- Add a heuristic backfill that populates `agent_call_log.quality_score` (0..1)
- Heuristic: was the output downstream-confirmed within N days?
  - Regime classification confirmed if next-month price move aligns with implied direction
  - Score-composer call confirmed if entry got a closed trade with positive P&L
  - Mention extraction call confirmed if extracted ticker survived a watchlist refresh
- CLI: `learning quality backfill [--since N_DAYS]` — recomputes quality_score for rows where it's NULL
- CLI: `learning quality summary` — average quality per agent_name + per call_type, JSON

### 5. Regime classifier accuracy
- Backtest harness: when `regime_classifications.label == "X"` at month M, did month M+1 / M+2 actually behave like X?
- "Behave like X" definition: per-regime price-action expectation (you define a config in `config/regime_outcomes.json` — e.g. `risk_on` expects SPY +>2% within 30d)
- Monthly rollup table — surface as CLI: `learning regime-accuracy [--lookback-months 12]`

### 6. Retraining triggers
- New module `src/macro_positioning/learning/retraining_triggers.py`
- Inputs: corpus depth (count of agent_call_log rows per agent), elapsed time since last retrain (config), accuracy degradation (from item 5)
- Output: `should_retrain(agent_name) -> {flag: bool, reason: str, evidence: dict}`
- Don't actually retrain — just signal
- CLI: `learning retrain-status` — JSON list of {agent, should_retrain, reason}

### 7. Model versioning
- Update LLM call sites to write `model_version` on every `agent_call_log` insert (currently only `model_name`)
  - Convention: `model_version = f"{model_name}@{prompt_version}"` so prompt churn is visible alongside model churn
- Backfill historical rows: `learning version backfill` — sets `model_version = model_name` where NULL (best-effort default since prompt_version isn't reconstructible from old rows)
- Add to `learning quality summary`: stratify quality by model_version

## File territory (yours to edit)

- `src/macro_positioning/learning/` — new modules: `quality_scorer.py`, `regime_accuracy.py`, `retraining_triggers.py`, `model_version_writer.py`
- `src/macro_positioning/learning/__init__.py` — re-exports
- `src/macro_positioning/cli.py` — extend the `learning` subcommand group
- `src/macro_positioning/brain/observability.py` (or wherever `agent_call_log` writes happen) — populate `model_version` on every write
- `config/regime_outcomes.json` — new config for item 5 expectations
- `tests/test_learning_*.py` — one test file per new module

## Off-limits (escalate to PM)

- `src/macro_positioning/db/schema.py` — schema is done; if you need MORE columns, ask
- `src/macro_positioning/dashboard/desk_data.py` — surfacing into SPA is a PM step
- `web/` — frontend
- `.claude/context/*`

## Done criteria

- Each module has working CLI surface returning JSON
- `agent_call_log.quality_score` populated for at least 50% of historical rows after `learning quality backfill` runs (acknowledge if real data is too sparse — backfill what you can)
- `agent_call_log.model_version` populated on every NEW write going forward
- `should_retrain()` returns sensible flags for at least the regime_classifier and narrative_synthesizer agents
- Tests with synthetic fixtures (don't depend on real DB state)
- Empty-data path doesn't crash — returns empty JSON arrays/objects
- `uv run pytest -q` passes (target: 364 + your new tests)

## Hand-back format

```
SHIPPED: ML learning loop items 4-7
Branch: claude/<slug>
Commits: <list>
Tests: <count> new
CLI demo: <paste output of `uv run python -m macro_positioning.cli learning quality summary` and `learning retrain-status`>
Backfill stats: <% of agent_call_log rows that got quality_score; same for model_version>
Schema requests: <if any further columns needed>
Open questions: <ambiguity in regime expectations, etc>
```

## Conventions

- `uv` for everything
- No LLM calls; this is pure analytics + schema population
- Pure functions taking `conn` so PM can wire results into `desk_data.py`
- Heuristics for quality scoring should be conservative — false positives here pollute future training data

# Worker brief: Heuristic scorers

You are a worker chat in the Macro Analyzer project. PM coordinates; you implement inside a declared file territory.

## Orientation (do this first)

Read in order:
1. `.claude/context/STATE.md` — current shipped state
2. `.claude/context/DECISIONS.md` — locked architectural decisions
3. `.claude/agents/app/CLAUDE.md` — application-agent conventions
4. `src/macro_brain/agents/technical_scorer/scorer.py` — reference: real heuristic scorer already shipped, mirror its shape
5. `src/macro_brain/orchestrator/composer.py` — how scorers are wired

## Scope

Replace four neutral-0.5 stubs with real heuristic scorers. NO LLM calls. NO new data sources. Read what's already in SQLite (`prices`, `mentions`, `source_outcomes`, `trade_scores`).

| Scorer | What it should measure |
|---|---|
| `volume_flow_confirmation` | Is recent volume confirming the price move? Compare last 5d avg volume vs 20d avg, signed by price direction over same window. |
| `sector_theme_strength` | For each ticker, look up its theme(s) in `config/watchlist.json`; aggregate mention-volume + recency across all tickers in that theme. Strong theme → high score. |
| `relative_strength` | Ticker's 20d return minus benchmark's 20d return (benchmark = SPY for equities, BTC for crypto, DXY for FX — config-driven map). Normalize via tanh. |
| `liquidity_alignment` | Use FRED FCI / NFCI series already in DB if present; if missing, return neutral 0.5 with a clear log. Higher when easing aligns with bullish thesis. |

## File territory (yours to edit)

- `src/macro_brain/agents/volume_flow_confirmation/scorer.py` (new)
- `src/macro_brain/agents/sector_theme_strength/scorer.py` (new)
- `src/macro_brain/agents/relative_strength/scorer.py` (new)
- `src/macro_brain/agents/liquidity_alignment/scorer.py` (new)
- `src/macro_brain/orchestrator/composer.py` (wire the new scorers; remove from stub list)
- `tests/macro_brain/agents/test_<scorer>.py` (new — one per scorer)
- `config/benchmarks.json` (new, for relative_strength) — `{"equity": "SPY", "crypto": "BTC-USD", "fx": "DXY"}`

## Off-limits (escalate to PM)

- `src/macro_positioning/db/schema.py` — schema changes
- `src/macro_positioning/dashboard/desk_data.py` — SPA snapshot
- `web/` — frontend
- `.claude/context/*` — STATE/DECISIONS/OPEN-QUESTIONS

## Done criteria

- Each scorer returns a 0..1 float and writes a `agent_call_log` row per the logging contract (`docs/logging_contract.md`)
- `composer.py` no longer lists these four in stub_components
- `uv run pytest -q` passes (target: 263 + your new tests)
- `uv run python -m macro_positioning.cli score run` produces visibly different scores from before (score spread should widen)
- Each scorer has at least one unit test covering: happy path, missing-data fallback, edge case (e.g. zero-volume day)

## Hand-back format

When done, post in this chat:

```
SHIPPED: heuristic scorers
Branch: claude/<slug>
Commits: <list>
Tests: <count> new, <count> total
Score spread before/after: <numbers from a sample run>
Open questions: <if any — schema needs, missing data, etc>
```

Then PM will review, merge to main, and update STATE.md.

## Conventions

- `uv` for everything. Never `pip`.
- Logging contract is non-negotiable — every scorer call writes to `agent_call_log` even though there's no LLM.
- Defaults to neutral 0.5 when input data is missing; log a warning, don't crash.
- Keep scorers pure functions of (ticker, asof_date, db_conn) where possible.

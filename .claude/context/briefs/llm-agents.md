# Worker brief: LLM agents (regime + narrative)

You are a worker chat in the Macro Analyzer project. PM coordinates; you implement inside a declared file territory.

## Orientation (do this first)

Read in order:
1. `.claude/context/STATE.md` — note the "STUBBED" section: regime_classifier and narrative_synthesizer are passthrough stubs you're replacing
2. `.claude/context/DECISIONS.md` — especially the 2026-05-09 LLM stack entry: **Gemini 2.5 Pro** for both, NOT Perplexity (that's reserved for `deep_research`, a separate future agent)
3. `.claude/agents/app/CLAUDE.md`
4. `docs/logging_contract.md` — every LLM call MUST write a complete `agent_call_log` row; this is the fine-tuning runway
5. `src/macro_brain/vision.py` — existing Gemini wiring; reuse the client / auth pattern
6. `src/macro_brain/agents/technical_scorer/scorer.py` — reference for scorer agent shape

## Scope

Wire two agents to Gemini 2.5 Pro, with strict logging. NO Perplexity, NO OpenAI — those belong to a future `deep_research` agent and are out of scope here.

### regime_classifier
- Input: recent FRED series snapshot (DGS10, DGS2, DXY, FCI, NFCI, EPU, etc — query from DB), recent macro mentions
- Output: regime label from a fixed enum (e.g. `risk_on`, `risk_off`, `late_cycle`, `disinflation`, `stagflation`, `transitioning`) + confidence 0..1 + 2-sentence rationale
- Persist: `regime_classifications` table (request schema from PM if not present)

### narrative_synthesizer
- Input: top-N recent newsletter/podcast items (query `mentions` + `sources`), current regime, top-scored tickers
- Output: 3-5 bullet "what the desk is talking about this week" — concise, no fluff, linkable to source IDs
- Persist: `narrative_snapshots` table (request schema from PM if not present)

## File territory (yours to edit)

- `src/macro_brain/agents/regime_classifier/` (replace the stub)
  - `agent.py` — the Gemini call
  - `prompt.py` — system + user prompt templates
  - `inputs.py` — DB queries to assemble context
- `src/macro_brain/agents/narrative_synthesizer/` (replace the stub)
  - same structure
- `src/macro_brain/orchestrator/composer.py` — wire the real agents; remove from stub list
- `tests/macro_brain/agents/test_regime_classifier.py`
- `tests/macro_brain/agents/test_narrative_synthesizer.py` — mock Gemini client, test prompt assembly + output parsing

## Off-limits (escalate to PM)

- `src/macro_positioning/db/schema.py` — both agents need new tables; ASK first with: `<table>(<cols>) :: <why>`
- `src/macro_positioning/dashboard/desk_data.py` — PM wires output into SPA
- `web/` — frontend
- `.claude/context/*`
- `src/macro_brain/agents/{volume_flow,sector_theme,relative_strength,liquidity_alignment}/` — that's the heuristic-scorers chat
- Any Perplexity / OpenAI / deep-research integration — out of scope per the locked LLM stack decision

## Done criteria

- Both agents call real Gemini and return structured output
- Every call writes a complete row to `agent_call_log` (input, output, prompt_version, latency_ms, cost_usd, model_version)
- Prompts are versioned (e.g. `regime_classifier.v1`); version stored in the call log
- Tests mock the Gemini client — no real API calls in the test suite
- `uv run python -m macro_positioning.cli score run` succeeds end-to-end
- Token-budget guards: per-call max tokens, log a warning if a call exceeds N USD (configurable)
- Failure mode: if Gemini errors, agent returns the previous stub-equivalent output (neutral) AND logs the error; never crashes the score pass

## Hand-back format

```
SHIPPED: LLM agents (regime + narrative)
Branch: claude/<slug>
Commits: <list>
Tests: <count> new (all mocked, no real API)
Sample output: <paste one regime classification + one narrative>
Cost per score run: <estimated USD>
Schema requests: <regime_classifications, narrative_snapshots specs>
Open questions: <prompt design decisions PM should ratify>
```

## Conventions

- `uv` for everything
- Logging contract is the whole point of this project; if a call doesn't log, it didn't happen
- Use Gemini 2.5 Pro specifically; the user has unlimited on the account
- Prompt templates as separate files so they're diff-able
- No web access, no live search — pure inference over DB-resident context

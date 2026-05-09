# Logging Contract — Training-Corpus Artifact Spec

**Owner:** Application Agent (enforces); Framework Agent (consumes for tuning)
**Status:** spec — every LLM-calling code path must conform
**Backing storage:** `agent_call_log` table (added in Phase 1 schema)

---

## Why this exists

The project's north-star principle is **fine-tuning-ready from day one**. Every LLM call must produce a structured logged artifact suitable as future training data. Without a strict logging contract, the system accumulates mountains of API calls but no usable training corpus — and the year-2 fine-tuning pivot becomes a 6-month archeology project.

This contract is non-negotiable. Code that calls an LLM without satisfying it does not ship.

---

## The contract

Every LLM call (regardless of which agent makes it, which model it uses, or what task it's for) must:

1. **Produce one row** in `agent_call_log` with all required fields populated
2. **Use a versioned prompt** — the exact prompt template + variables must be reproducible from `prompt_version`
3. **Store input + output as JSON** — enough detail to recreate the call exactly
4. **Capture context separately** — what surrounding state influenced this call
5. **Track latency, tokens, cost** — for observability + cost attribution
6. **Allow later attribution** — when a trade closes, this row should be findable as a contributor

---

## Schema

```sql
CREATE TABLE agent_call_log (
    call_id              TEXT PRIMARY KEY,        -- UUID
    agent_name           TEXT NOT NULL,           -- e.g., 'regime_classifier'
    called_at            TEXT NOT NULL,           -- ISO 8601 UTC
    model_provider       TEXT NOT NULL,           -- 'gemini' | 'anthropic' | 'openai' | 'n8n' | 'ollama'
    model_name           TEXT NOT NULL,           -- e.g., 'gemini-2.5-pro'
    prompt_version       TEXT NOT NULL,           -- e.g., 'regime_classifier@v3'
    input_payload_json   TEXT NOT NULL,           -- the rendered prompt + structured inputs
    output_payload_json  TEXT NOT NULL,           -- raw model output (or structured parse)
    context_json         TEXT,                    -- surrounding state (regime at call time, recent decisions, etc.)
    latency_ms           INTEGER,
    input_tokens         INTEGER,
    output_tokens        INTEGER,
    estimated_cost_usd   REAL,
    success              INTEGER NOT NULL,        -- 0 or 1
    error_message        TEXT,
    attributed_setup_id  TEXT,                    -- nullable; populated post-hoc
    attributed_trade_id  TEXT,                    -- nullable; populated when trade closes
    attributed_outcome_pnl REAL                   -- nullable; populated when trade closes
);
```

---

## Field-by-field spec

### `call_id` (TEXT, PK)
UUID v4. Generated client-side before the call so failed calls also get logged.

### `agent_name` (TEXT)
The production agent making the call. Examples:
- `regime_classifier`
- `narrative_synthesizer`
- `technical_scorer`
- `volume_analyzer`
- `chart_vision`
- `psychology_evaluator`
- `sector_theme_scorer`
- `orchestrator`

For ad-hoc / experimental calls, prefix with `experiment_` (e.g., `experiment_thesis_drafter`). These get filtered out of training corpus by default.

### `called_at` (TEXT)
ISO 8601 UTC. Use `datetime.now(timezone.utc).isoformat()`. Not local time. Not naive.

### `model_provider`, `model_name` (TEXT)
- Provider: lowercase identifier — `gemini`, `anthropic`, `openai`, `n8n`, `ollama`, `together`, `groq`, etc.
- Name: the exact model identifier — `gemini-2.5-pro`, `claude-sonnet-4-5`, `qwen2.5-vl-72b-instruct`. NOT a friendly alias.

### `prompt_version` (TEXT)
Versioned prompt identifier in the form `{agent_name}@v{N}` or `{agent_name}@{git_short_sha}`. Examples:
- `regime_classifier@v3`
- `narrative_synthesizer@a1b2c3d`

Prompts live in `macro-brain/agents/{agent_name}/prompts/` as numbered files (`v1.md`, `v2.md`, `v3.md`). When you update a prompt, increment the version. NEVER edit a deployed prompt version in place — that breaks reproducibility.

### `input_payload_json` (TEXT)
Full JSON dump of:
- The rendered prompt (after variable interpolation)
- The structured inputs (e.g., document content, FRED series snapshot, chart image hash)
- Any system instructions or tool definitions passed to the model

Must be sufficient to **recreate the exact call**. If you can't run the call again from this field, the field is incomplete.

### `output_payload_json` (TEXT)
Raw model output. If the agent parses output into a structured object, store both:
```json
{
  "raw": "...full model response...",
  "parsed": { "regime": "dovish_liquidity_wave", "confidence": 0.78, ... }
}
```

Store raw even when parsing succeeds — parsing logic may change later and we want to re-parse historical outputs.

### `context_json` (TEXT, nullable)
Surrounding state that influenced the call but wasn't part of the prompt:
- Active regime at call time (`regime_id` reference)
- Recent decisions (last 5 from `decisions` table)
- Active trades count
- Time-of-day, day-of-week (for behavior pattern analysis)
- Source freshness state for any documents in the input

This is what makes the training data **rich**. Without it, future fine-tuning has only the prompt — context-free.

### `latency_ms`, `input_tokens`, `output_tokens`, `estimated_cost_usd`
Observability fields. Cost should use the provider's published per-token pricing at call time (capture at log time, not at query time, so historical cost analysis is stable).

### `success`, `error_message`
- `success = 1` if the call returned and parsed correctly
- `success = 0` if anything failed; error_message captures what
- Failed calls STILL log. They are negative training examples.

### Attribution fields (nullable, populated post-hoc)

When a trade is logged in `trades` table:
- `attributed_setup_id` populated for all `agent_call_log` rows that contributed to that setup's `trade_score`
- `attributed_trade_id` populated for the same rows

When that trade closes:
- `attributed_outcome_pnl` populated with the realized P&L %

This is the link that turns logs into training pairs: `(input, output, context) → outcome`.

---

## How attribution works

```
1. Document arrives → narrative_synthesizer call → log row A
2. FRED data + recent docs → regime_classifier call → log row B
3. Chart screenshot → chart_vision call → log row C
4. Orchestrator composes A + B + C → trade_score → log row D (attribution_setup_id = setup_X)
   ↓ at this point, rows A, B, C also get attribution_setup_id = setup_X (orchestrator's job)
5. User logs trade in dashboard (manual entry) → trades row created with setup_id = setup_X
   ↓ rows A, B, C, D get attribution_trade_id = trade_Y
6. Trade closes (user logs outcome) → trades row updated with pnl = +12%
   ↓ rows A, B, C, D get attributed_outcome_pnl = 12.0
```

Now we have four rows of `(prompt, output, context) → realized P&L`. Stack ~1000 of those across all agents and you have a real training corpus.

---

## What goes IN the training corpus

For fine-tuning, we filter `agent_call_log` to rows where:
- `success = 1`
- `attributed_outcome_pnl IS NOT NULL` (we know how it went)
- `agent_name` is not prefixed `experiment_`
- The prompt was for a *generation* task (not pure classification — those train as small classifiers via Framework Agent)

Negative examples (losing trades) are AS valuable as positive ones — the model needs to learn what NOT to recommend.

---

## What does NOT go in `agent_call_log`

- Pre-tagging keyword routing (no LLM call) — those go in a `pre_tagger_log` if we want them
- Heuristic-only scoring (e.g., `psychology_evaluator` checklist) — no LLM = no log row
- Database queries
- Internal Python function calls

If the call goes to an external LLM API, it logs. If it doesn't, it doesn't.

---

## Implementation pattern

A single helper function in `macro-brain/api/log.py` (or analogous):

```python
def log_agent_call(
    agent_name: str,
    model_provider: str,
    model_name: str,
    prompt_version: str,
    input_payload: dict,
    call_fn: Callable[[], Awaitable[dict]],
    context: dict | None = None,
) -> dict:
    """Wrap an LLM call so it always logs. Returns the model output dict.

    The caller passes a closure `call_fn` that performs the actual LLM call.
    This wrapper times it, catches errors, and writes to agent_call_log
    regardless of success/failure.
    """
    call_id = str(uuid.uuid4())
    started = time.monotonic()
    success = False
    error_message = None
    output_payload = {}
    try:
        output_payload = call_fn()
        success = True
        return output_payload
    except Exception as exc:
        error_message = str(exc)
        raise
    finally:
        latency_ms = int((time.monotonic() - started) * 1000)
        _write_log_row(
            call_id=call_id,
            agent_name=agent_name,
            called_at=datetime.now(timezone.utc).isoformat(),
            model_provider=model_provider,
            model_name=model_name,
            prompt_version=prompt_version,
            input_payload_json=json.dumps(input_payload),
            output_payload_json=json.dumps(output_payload),
            context_json=json.dumps(context) if context else None,
            latency_ms=latency_ms,
            input_tokens=output_payload.get("usage", {}).get("input_tokens"),
            output_tokens=output_payload.get("usage", {}).get("output_tokens"),
            estimated_cost_usd=_compute_cost(model_provider, model_name, output_payload.get("usage", {})),
            success=int(success),
            error_message=error_message,
        )
```

Every production agent calls this wrapper. If you find yourself calling an LLM SDK directly without going through this wrapper, **stop and refactor**.

---

## Migration plan for existing brain code

The current `src/macro_positioning/brain/` already calls Gemini via N8N. Phase 4 of the project plan ports brain code into `macro-brain` repo and slots in the wrapper above. Existing un-logged calls are tolerated until that port; new calls (from Phase 1 forward) must conform.

---

## Validation

- `agent_call_log` row count grows monotonically (no deletions)
- 100% of rows have non-null `agent_name`, `called_at`, `model_provider`, `model_name`, `prompt_version`, `input_payload_json`, `output_payload_json`
- 100% of `success=1` rows have non-empty `output_payload_json`
- `prompt_version` strings appear in `macro-brain/agents/{agent_name}/prompts/` (CI check)
- `attributed_outcome_pnl IS NOT NULL` rows can be reconstructed into valid (prompt, completion) training pairs

---

## Privacy / sensitivity note

The user's manual notes can contain personal trading-account details, P&L sizes, etc. When logging:
- Strip account numbers, broker names, dollar P&L (keep percent P&L only)
- Strip API keys from any payload (defensive sanitization on `input_payload_json` write)
- Treat the database file as sensitive — ignore from any backup/sharing without explicit user opt-in

---

## When this contract changes

Append a changelog entry. Schema changes require a migration. Field additions are safe (nullable); field removals/renames need a deprecation cycle.

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-05-08 | Initial contract; `agent_call_log` table created in schema.py |

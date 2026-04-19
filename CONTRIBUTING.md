# Contributing to macro-analyzer

## Branching Model

We run **parallel workstreams** on dedicated branches to allow multiple
Claude Code / Codex agents to work simultaneously without collisions.

See [`docs/workstreams.md`](docs/workstreams.md) for the full stream
breakdown, file ownership, and kickoff prompts.

```
main                            (protected, merge via PR only)
├── stream-a-ingestion          (Ingestion layer work)
├── stream-b-brain              (LLM / Brain layer work)
├── stream-c-dashboard          (UI / Dashboard work)
└── stream-d-integration        (Integration + Ops work)
```

---

## Rules for Multi-Agent Development

### 1. Stay in your lane

Each stream owns a specific subset of paths. Do NOT modify paths owned by
another stream. If you genuinely need to, pause and coordinate via
GitHub issue.

### 2. Pull before you push

```
git checkout stream-b-brain
git pull origin main         # sync any main changes
# ... work ...
git push origin stream-b-brain
```

### 3. Shared files require coordination

These files touch multiple streams. Changes must be discussed:
- `src/macro_positioning/core/models.py`
- `src/macro_positioning/core/settings.py`
- `src/macro_positioning/api/main.py`
- `src/macro_positioning/pipelines/run_pipeline.py`
- `pyproject.toml`
- `README.md`
- `data/checklist.json`

Preferred pattern: open a quick issue, confirm no collisions, then make
the change on whichever stream needs it first.

### 4. Commits are atomic

One logical change per commit. Clear message:
```
Stream B: add retry logic to Gemini backend

Uses tenacity with exponential backoff, max 3 retries on timeout/5xx.
Logs each retry attempt to brain_calls.
```

### 5. Tests must stay green

Run before every push:
```
python -m pytest tests/ -q
```

Never merge a PR that fails CI.

---

## Setup

```bash
# Clone
git clone https://github.com/thommi2phones/macro-analyzer.git
cd macro-analyzer

# Create venv (needs Python 3.11+, recommended 3.13)
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e .

# Copy env template
cp .env.example .env
# Edit .env with your API keys (MPA_GEMINI_API_KEY, MPA_FRED_API_KEY, etc.)

# Run tests
python -m pytest tests/ -q

# Launch API
uvicorn macro_positioning.api.main:app --reload --port 8000
```

Visit http://localhost:8000/dashboard

---

## LLM Credentials

The Brain supports multiple backends. Set at least one:

```bash
# Primary — Gemini (recommended)
MPA_GEMINI_API_KEY=...

# Alternative / escalation — Claude
MPA_ANTHROPIC_API_KEY=...

# Optional — local Ollama for dev
MPA_OLLAMA_BASE_URL=http://localhost:11434
MPA_OLLAMA_MODEL=qwen2.5:14b
```

Routing is controlled by:
```
MPA_BRAIN_PRIMARY_BACKEND=gemini        # default for synthesis
MPA_BRAIN_VISION_BACKEND=gemini         # default for chart vision
MPA_BRAIN_ESCALATION_BACKEND=anthropic  # when escalate=True
```

---

## Personal Gmail (Stream A)

The personal Gmail connector requires separate OAuth credentials from
any work/shared Gmail:

```bash
python -c "from macro_positioning.ingestion.personal_gmail import print_setup_instructions; print_setup_instructions()"
```

---

## Integration with tactical-executor

When changing integration contracts:

1. Modify `src/macro_positioning/integration/contracts.py`
2. Bump `CONTRACT_VERSION`
3. Run `python scripts/export_integration_schema.py`
4. Copy the new `integration_schema/macro_schema_v*.json` into the
   tactical-executor repo at `/integration/macro_schema.json`
5. Update `CONTRACT_VERSION` in `webhook/macro_integration.js` in the
   tactical repo
6. Commit changes to both repos in the same work session

See [`docs/integration_with_trading_agent.md`](docs/integration_with_trading_agent.md).

---

## Pull Request Template

```
## Summary
[Brief description]

## Stream
- [x] Stream A (Ingestion)
- [ ] Stream B (Brain)
- [ ] Stream C (Dashboard)
- [ ] Stream D (Integration)

## Changes
- ...

## Tests
- [ ] All existing tests pass
- [ ] New tests added for new functionality
- [ ] Manual testing completed

## Shared files touched
List any files from the "shared files" section above and explain why.

## Dependencies
Any new entries in pyproject.toml?
```

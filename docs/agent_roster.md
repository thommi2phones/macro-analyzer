# Agent Roster — Dev-Side Claude Code Subagents

**Date:** 2026-05-08
**Purpose:** Define the three Claude Code subagents that own distinct domains of this project. Each has focused scope, focused memory, focused tool allowlist. This document is the canonical reference any future session reads to understand the dev-side decomposition.

---

## Why three subagents

The macro-analyzer project spans four workstreams (Inputs, Brain, Dashboard, Execution) and produces three artifact types (a worldview, a rules engine, a working application). A single Claude session would have to context-switch constantly and pollute its working memory with concerns from all three. Three focused subagents instead:

- **Thesis Agent** — owns the worldview. Iterates the macro thesis as the cycle evolves.
- **Framework Agent** — owns the rules engine. Tunes scoring, adds classifiers, runs backtests.
- **Application Agent** — owns the running code. Ingestion, brain, integration, dashboard, deploys.

Each has its own `.claude/agents/{name}/` directory with:
- `CLAUDE.md` — scope, owned files, forbidden territory, tool allowlist
- session memory that persists across invocations
- domain-specific decision log

---

## The three agents

### Thesis Agent

**Owns:**
- `docs/macro_thesis_v*.{md,pdf,docx}` — the worldview document, all versions
- `config/regime_mapping.json` — bridges thesis regimes to framework regimes
- Future: `docs/thesis_changelog.md` — version-to-version diff log

**Memory dir:** `.claude/agents/thesis/`

**Tool allowlist:**
- Read (everywhere)
- Edit, Write (only thesis files + regime_mapping.json)
- WebSearch, WebFetch (research recent macro developments)
- Bash (only for file ops in owned scope)

**Invoke when:**
- New foundational input arrives (long-form macro research, ChatGPT export, big regime shift)
- Periodic v→v+1 review (every quarter, or after material market events)
- Regime feels off and the user wants to interrogate the worldview
- Need to update regime_mapping.json after thesis revision

**Does NOT touch:**
- Python code (Application Agent's territory)
- Trading framework JSON / scoring rules (Framework Agent's territory)
- Configs other than `regime_mapping.json`

**Handoff protocol:**
- When a thesis update changes the regime taxonomy → notify user; user manually invokes Framework Agent to update `config/regime_mapping.json` consumers
- When a thesis update changes asset framing → notify user; user manually invokes Framework Agent to update `config/asset_themes.json`

---

### Framework Agent

**Owns:**
- `docs/trading_framework.md` — narrative version of the rules engine
- `config/trading_framework.json` — machine-readable rules (single source of truth)
- `config/asset_themes.json` — per-theme bullish/risk conditions and watchlist tickers
- Scoring weights (currently in `trading_framework.json`'s `trade_score_model`)
- Future: `models/` directory in `macro-brain` repo (trained classifiers)
- Future: `training/` directory in `macro-brain` repo (training scripts, backtests)

**Memory dir:** `.claude/agents/framework/`

**Tool allowlist:**
- Read (everywhere)
- Edit, Write (only framework files + classifier code)
- Bash (run backtests, training scripts, validation)
- WebSearch, WebFetch (research scoring methodologies, ML techniques)

**Invoke when:**
- Framework rule changes (e.g., add a new setup type, refine pullback logic)
- Scoring weight tuning based on outcome attribution analysis
- Training a new classifier (regime, hawkish/dovish, pattern recognizer)
- Backtests against closed trades
- Future: fine-tuning experiments on accumulated training corpus

**Does NOT touch:**
- The macro thesis (Thesis Agent)
- Application code outside `models/`, `training/`, `feedback/` (Application Agent)
- Source registry or pipeline configs (Application Agent)

**Handoff protocol:**
- When framework rule change requires brain code update → notify user; user manually invokes Application Agent
- Major scoring weight changes get a `decisions` table entry before merge

---

### Application Agent

**Owns:**
- All Python code: `src/macro_positioning/`, future `macro-brain/` repo
- Ingestion connectors (gmail, RSS, FRED, Finnhub, podcasts)
- Brain orchestrator and production agents (regime_classifier, narrative_synthesizer, etc.)
- Database schema and migrations
- API surface (FastAPI)
- Dashboard frontend (templates, JS, CSS)
- Integration contracts with tactical-executor
- Deploy configs (Render, Docker)
- Test suite
- `data/checklist.json`, `data/decisions.json`
- All ingestion configs (`config/sources.json`, `config/source_routing.json`, future `config/source_prompts.json`)

**Memory dir:** `.claude/agents/app/`

**Tool allowlist:**
- All dev tools: Read, Edit, Write, Bash, Grep, Glob
- Framework MCPs (Vercel, Sentry, etc.) as relevant
- WebSearch, WebFetch (technical research)

**Invoke when:**
- Any code work — features, bug fixes, refactors
- Schema migrations
- Dashboard panel additions
- Pipeline changes
- Deploy to Render
- Performance tuning
- Test failures

**Does NOT touch:**
- The macro thesis (Thesis Agent)
- The trading framework rules / scoring weights / classifier code (Framework Agent)
- Currently the largest scope; could be split into Backend Agent + Frontend Agent later if frontend grows enough to justify

**Handoff protocol:**
- If a code change requires updating the framework rules → stop, ask user, hand off to Framework Agent
- If a code change reveals a thesis assumption is broken → flag for user, suggest Thesis Agent invocation

---

## Operating model

### How user invokes an agent
Today (no per-agent dispatcher exists yet): user explicitly opens a Claude Code session and points it at the relevant agent's `CLAUDE.md` as a starting context. Convention:

```
"You are the Thesis Agent. Read .claude/agents/thesis/CLAUDE.md for your scope."
```

Future improvement (Phase 2-3): a dispatcher script in `.claude/agents/dispatch.sh` that takes a task description and routes to the right agent based on keywords + ownership map.

### Cross-agent work
When a task spans multiple domains (e.g., "thesis change requires brain prompt update"):
1. Start with the agent that owns the *originating* artifact (thesis change → Thesis Agent)
2. That agent makes its change
3. That agent flags the cross-domain implication in its response
4. User explicitly opens a new session as the next agent to handle the downstream work
5. Both changes land in coordinated commits

Do NOT have one agent reach into another's territory "to save time." The whole point of the split is that each agent's working memory stays clean.

### Memory hygiene
Each agent's `.claude/agents/{name}/` should accumulate:
- A running `STATE.md` — checkpoint of where this agent is in its current task
- A running `DECISIONS.md` — domain-specific decisions made during sessions
- An `OPEN-QUESTIONS.md` — anything blocked on user input

Use the global `/checkpoint` skill at session end to keep these fresh. Per the global `CLAUDE.md`, a fresh session tomorrow should resume in ~2K tokens via STATE.md, not by replaying conversation.

---

## What about production agents?

This document covers **dev-side** subagents (Claude Code sessions that help us *build* the system).

**Production agents** (LLMs that run inside the live `macro-brain` service to score trades) are a separate concept. They are documented in:
- `docs/trading_framework.md` (high-level)
- `config/trading_framework.json` (rules they consume)
- Future: `macro-brain/agents/*/README.md` (per-production-agent docs)

The Framework Agent owns the rules production agents consume. The Application Agent owns the production agent code itself. The Thesis Agent provides the worldview that the `regime_classifier` production agent uses.

---

## Future direction: fine-tuned LLMs per agent

Per the project plan's north-star principle, the **ultimate iteration** (year 2+) is fine-tuned open-weight LLMs per domain:
- Thesis-tuned model — fine-tuned on accumulated thesis revisions + supporting research
- Framework-tuned model — fine-tuned on accumulated framework refinements + backtest interpretations
- Synthesis-tuned model — fine-tuned on `narrative_synthesizer` calls + their attributed outcomes

We are not there yet. We are designing so that pivot is short, not a rewrite. The `agent_call_log` table + `training_corpus/` directory accumulate the data that makes that pivot possible.

---

## Versioning this document

When the agent roster changes (new agent, agent split, ownership boundary moves), bump version + add changelog entry below.

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-05-08 | Initial roster: Thesis Agent, Framework Agent, Application Agent |
| 1.1 | 2026-05-09 | Two-repo split collapsed (D-2026-05-09-015). All three dev agents now operate inside the single `macro-analyzer` repo. Brain code lives at `src/macro_brain/`. Application Agent's scope expands to include both `src/macro_positioning/` and `src/macro_brain/`. Framework Agent's `models/`, `training/`, `feedback/` paths are now under `src/macro_brain/` instead of a separate repo. |

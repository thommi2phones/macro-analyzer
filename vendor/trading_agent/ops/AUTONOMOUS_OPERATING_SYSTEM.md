# Autonomous Operating System (Codex-First, Claude-on-Gate)

## 1) Mission
Run continuous project iteration with AG as manager, using Codex for primary execution and reserving Claude for selective high-value gates.

## 2) Roles
- **AG / main (Codex):** orchestration, planning, implementation, testing, reporting.
- **Claude lane (disabled by default):** only for final verification/pre-push or high-risk debugging.

## 3) Loop Cadence
Each cycle runs:
1. **Plan** (pick next highest-value task)
2. **Execute** (small, shippable change)
3. **Verify** (tests/lint/sanity)
4. **Report** (what changed, evidence, blockers)
5. **Queue** (next 1-3 tasks)

Cycle target: 20–45 minutes per unit.

## 4) Guardrails
- No destructive commands unless explicitly approved.
- Keep changes scoped and reversible.
- Run verification before marking complete.
- If blocked >15 minutes, produce unblock request and move to next queued task.
- Never store API secrets in chat logs or repo files.

## 5) Claude Escalation Gates (OFF until key provided)
Use Claude only when a task is at one of these gates:
- `pre-merge`
- `pre-release`
- `high-risk-refactor`
- `codex-stalled`

When gate triggers:
- produce a focused prompt + artifacts for Claude review
- collect findings
- apply final hardening pass

## 6) Task Prioritization
Priority order:
1. blockers to core functionality
2. reliability/stability
3. performance
4. developer velocity
5. nice-to-have features

Scoring: Impact (1-5) × Confidence (1-5) ÷ Effort (1-5)

## 7) Reporting Format
For each cycle:
- **Goal**
- **Changes made**
- **Verification evidence**
- **Risks/assumptions**
- **Next actions**
- **Needs-human-decision (if any)**

## 8) Human Decision Queue
Any item requiring your input goes to `ops/DECISIONS_NEEDED.md`.
All available autonomous work continues in parallel.

## 9) Launch Conditions
Required:
- repo path confirmed
- top objective confirmed

Optional:
- test command(s) confirmed
- branch strategy confirmed

## 10) Run State
Current mode: **SETUP COMPLETE / WAITING FOR OBJECTIVE**

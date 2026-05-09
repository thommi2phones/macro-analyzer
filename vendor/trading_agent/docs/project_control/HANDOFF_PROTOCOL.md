# Claude ↔ Codex ↔ James Handoff Protocol (Strict)

## Goal
Zero-ambiguity handoffs across systems.

## Required Message Format

```text
[HANDOFF]
From: <system>
To: <system>
Task-ID: <unique-id>
Priority: P0|P1|P2
Context: <1-3 lines>
Inputs: <paths/refs>
Expected Output: <artifact + schema>
Validation: <test/criteria>
Deadline: <timestamp>
Risks: <known risks>
Status: READY|BLOCKED|DONE
```

## Rules
1. No work accepted without `Task-ID`.
2. Every output must include validation evidence.
3. If blocked >20 minutes, escalate to James with blocker + two options.
4. Conflicts resolved by policy order:
   - Contract validity
   - Confidence threshold
   - Freshness
   - Risk policy
5. Never overwrite schema without explicit version bump (`v1 -> v1.1`).

## Status Cadence
- Update interval: every 90 minutes during active build.
- James posts consolidated control summary:
  - Completed
  - In progress
  - Blocked
  - Next critical path move

## Artifact Naming
- `specs/MVP-SPEC-v1.md`
- `schemas/signal-envelope.v1.json`
- `reports/dayN-status.md`
- `tests/e2e-smoke-v1.md`

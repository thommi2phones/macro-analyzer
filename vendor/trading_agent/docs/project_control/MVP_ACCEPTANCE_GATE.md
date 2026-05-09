# MVP Acceptance Gate (Hard Yes/No)

Status: Locked
Date: 2026-03-02
Owner: Thomas

## Core Gate

MVP is **LIVE** when this full chain works end-to-end:

**poll → inbox → process → signal → alert → trade execution**

## Pass Criteria

1. End-to-end chain completes successfully without manual intervention.
2. No duplicate executions for the same setup/event (idempotency enforced).
3. Every stage emits traceable logs with linked IDs (event_id → signal_id → execution_id).
4. Failure path is covered with alert + retry/fallback behavior.
5. At least 3 successful test cycles on distinct events/assets.

## Recommended Reliability Window

- Minimum: one full execution session.
- Preferred: 24h continuous operation with stable behavior.

## Verdict Rule

- If all criteria pass: **MVP = LIVE**
- If any criterion fails: **MVP = NOT LIVE**

# Agent Launch Checklist

## Phase 1 — Define
- [ ] Confirm agent names and owners
- [ ] Confirm required outputs per agent
- [ ] Confirm escalation path and SLA

## Phase 2 — Spawn Lanes
- [ ] Spawn Engineering lane (ACP persistent session)
- [ ] Spawn Research lane (ACP persistent session)
- [ ] Spawn Technical lane (ACP persistent session)
- [ ] Spawn Trade Analyst lane (ACP persistent session)
- [ ] Keep Strategy Office in main thread (Thomas + James)

## Phase 3 — Wire Handoffs
- [ ] Enforce handoff template with task_id + expected output + validation
- [ ] Enforce BLOCKED escalation <= 20 min
- [ ] Enforce evidence requirement before DONE

## Phase 4 — Operate
- [ ] 90-min consolidated status updates
- [ ] Daily review report
- [ ] Track throughput: completed, blocked, rework count

## First Dispatch Packets (ready-to-send)

### ENG-001
- Build/maintain MVP execution chain reliability
- Validation: e2e chain + logs + no duplicates

### RES-001
- Produce market regime and watchlist update template
- Validation: daily structured report format

### TECH-001
- Formalize setup scoring rubric (pattern/fib/indicator)
- Validation: deterministic score output on sample setups

### TA-001
- Analyze completed trade history for edge trends and rule drift
- Validation: setup-tier performance report + top 3 evidence-backed rule adjustments

## Governance
- Strategy Office approves all P0 scope changes
- Execution & Risk can veto unsafe actions
- Final launch decision requires MVP acceptance gate pass

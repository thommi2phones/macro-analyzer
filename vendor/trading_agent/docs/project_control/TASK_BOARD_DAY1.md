# Day 1 Task Board (Execute Now)

## P0 — Must Complete Today

1. **MVP Scope Freeze**
   - [ ] List in-scope features (P0)
   - [ ] List out-of-scope features (P1/P2)
   - Owner: Thomas + James

2. **Shared Signal Contract v1**
   - [ ] Define `SignalEnvelope` schema:
     - `id`, `timestamp`, `domain`, `signal_type`, `action`, `confidence`, `rationale`, `inputs_ref`, `ttl`
   - [ ] Define invalid/unknown state handling
   - Owner: Codex

3. **System Role Assignment**
   - [ ] Codex: infra/orchestration/control APIs
   - [ ] Claude: strategy logic quality + edge-case analysis
   - [ ] James: coordination, arbitration, progress control
   - Owner: James

4. **Backlog + Priority**
   - [ ] Create P0/P1/P2 list
   - [ ] Add owner + ETA + dependency
   - Owner: James

5. **Acceptance Tests Draft**
   - [ ] E2E test case: ingest -> signal -> orchestrate -> output
   - [ ] Failure test case: missing input + retry/fallback
   - Owner: Claude + Codex

## Day 1 Exit Criteria
- [ ] MVP-SPEC v1 published
- [ ] Schema contract locked
- [ ] Owners assigned for all P0 tasks
- [ ] Day 2 inputs ready

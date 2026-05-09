# Agent Organization Blueprint (v1)

## Objective
Create a multi-agent operating model for the Trading + Market Signal system that can run 24/7 with Thomas steering.

## Agent Topology

1. Strategy Office (James + Thomas)
- Role: priorities, risk posture, launch/no-launch decisions
- Inputs: all agent summaries
- Outputs: approved objectives, thresholds, gate decisions

2. Market Research Agent
- Role: market regime, macro/news context, opportunity ranking
- Outputs:
  - `regime_state` (risk-on/risk-off/neutral)
  - `watchlist_updates`
  - `thesis_notes`

3. Engineering Agent
- Role: pipeline/infrastructure/reliability
- Owns: poll -> inbox -> process -> signal -> alert -> execution chain
- Outputs:
  - implementation diffs
  - reliability metrics
  - incident reports

4. Chart/Technical Analyst Agent
- Role: structure/pattern/fib/indicator confluence scoring
- Outputs:
  - setup validation
  - confluence score
  - invalidation levels

5. Execution & Risk Agent
- Role: position sizing, stop/TP policies, risk controls
- Outputs:
  - size class decision
  - exposure checks
  - override/kill-switch recommendations

6. Trade Analyst Agent
- Role: post-trade intelligence and edge evolution
- Inputs: completed trades, screenshots, execution logs, setup metadata
- Outputs:
  - setup-type win/loss trends
  - confluence-tier performance shifts
  - R-multiple distribution and drift alerts
  - rule-refinement proposals backed by evidence

## Contract (Required fields for every agent output)

```json
{
  "task_id": "string",
  "agent": "strategy|research|engineering|technical|risk",
  "timestamp": "ISO-8601",
  "status": "READY|BLOCKED|DONE",
  "confidence": 0.0,
  "summary": "string",
  "evidence": ["string"],
  "risks": ["string"],
  "recommended_action": "string"
}
```

## Arbitration Order (when outputs conflict)
1. Hard risk policy and safety constraints
2. Data freshness / schema validity
3. Confidence threshold (>=0.72)
4. Strategy priority
5. Manual override by Thomas

## Cadence
- Agent heartbeat: every 90 minutes while active build window is open
- Strategy Office consolidation: every 90 minutes
- Daily review: 1 summary with completed / blocked / next critical move

## Implementation Pattern (OpenClaw)
- Use ACP sessions for specialist coding/research lanes.
- Keep sessions persistent/threaded for continuity.
- Assign one owner lane per major function (no duplicate ownership).

## Initial Assignment Matrix
- Strategy Office: James + Thomas
- Research: Claude lane (analysis-heavy)
- Engineering: Codex lane (implementation-heavy)
- Technical: Claude lane (chart logic + confluence interpretation)
- Risk: James policy layer + implementation hooks in Engineering lane

## Success Criteria
- No ambiguous ownership for any P0 task.
- All outputs conform to contract.
- Conflicts resolved through arbitration policy.
- End-to-end MVP acceptance gate remains source of truth.

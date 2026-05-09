# Cluster B Protocol (Claude Code — Execution)

## Role
Cluster B claims tasks from the shared coordination bus, executes code/test/deploy work,
and returns results. Cluster A (GPT/Codex PM) creates and prioritizes tasks.

## Coordination Bus Location
```
/Users/thom/Documents/Personal/Codex Projects/Trading Agent Codex/coordination/
```
Override with `COORDINATION_DIR` env var if needed.

GitHub remote: `https://github.com/thommi2phones/Trading-Agent-V1-CODEX.git`

## Worker Script
```bash
python3 scripts/task_worker.py <command>
```

### Commands

| Command | Description |
|---------|-------------|
| `list` | Show all pending tasks |
| `claim` | Claim the next pending task (FIFO) |
| `claim <task_id>` | Claim a specific task |
| `complete <task_id> "summary" ["artifacts"]` | Mark task done with results |
| `block <task_id> "reason"` | Block task, hand back to Cluster A |
| `create "title" "desc" "bucket" [priority] [criteria]` | Create task for Cluster A |
| `status` | Dashboard: counts + recent events |

### Buckets
Research, Strategy Design, Backtesting, Risk Modeling, Execution Logic,
Monitoring, Capital Allocation, Post Trade Review

### Priorities
P1 (critical), P2 (normal), P3 (low)

## Workflow

### Receiving work from Cluster A
1. `python3 scripts/task_worker.py list` — see what's pending
2. `python3 scripts/task_worker.py claim` — claim next task
3. Execute the work (code, test, deploy)
4. `python3 scripts/task_worker.py complete <id> "summary" "artifacts"` — done
5. Git commit + push from Codex repo so Cluster A sees the result

### Sending work to Cluster A
1. `python3 scripts/task_worker.py create "title" "desc" "bucket"` — creates pending task
2. `handoff_to: cluster_a` is set automatically
3. Git commit + push from Codex repo

### Blocking
If a task can't be completed:
1. `python3 scripts/task_worker.py block <id> "reason"`
2. Task moves to `blocked/`, Cluster A sees it and decides next steps

## Git Sync (CRITICAL)
After any task_worker operation, sync to GitHub:
```bash
cd "/Users/thom/Documents/Personal/Codex Projects/Trading Agent Codex"
git add coordination/
git commit -m "coordination: <action> <task_id>"
git push origin main
```

Both clusters read from the same GitHub repo. Without push, the other cluster can't see changes.

## OC Worker (Operational Changes)
```bash
python3 scripts/oc_worker.py <command>
```

| Command | Description |
|---------|-------------|
| `list` | Show pending OC proposals |
| `show <oc_id>` | Full details of an OC |
| `approve <oc_id> "reason"` | Approve an OC |
| `deny <oc_id> "reason"` | Deny an OC |
| `bridge` | Convert approved OCs into execution tasks |
| `generate` | Generate OC proposals from trade_history.json |
| `status` | OC dashboard |

### OC Flow
1. Cluster A's `oc_generator.js` or Cluster B's `oc_worker.py generate` creates OC proposals
2. Human reviews: `approve` or `deny`
3. `bridge` converts approved OCs into tasks in `coordination/tasks/pending/`
4. Normal task lifecycle takes over (claim → execute → complete)

### OC Generation Signals (from trade_history.json)
- Low confluence rate (>50% of scored trades <= 2)
- Missing entry/TP data (>15% incomplete)
- Setup type over-concentration (>35% single type)
- Directional imbalance (>80% one direction)

## Event Trail
Every action emits a JSON event to `coordination/events/`. This is the audit log.
Events are append-only — never delete or modify them.

## Schema Compliance
Tasks must match `coordination/schema/task.schema.json`.
Events must match `coordination/schema/event.schema.json`.
The Python worker enforces this by construction.

## Directory Structure
```
coordination/
├── tasks/
│   ├── pending/        # New tasks (Cluster A creates, Cluster B reads)
│   ├── in_progress/    # Claimed by Cluster B
│   ├── done/           # Completed (results + artifacts)
│   └── blocked/        # Needs intervention from Cluster A
├── events/             # Append-only audit log
├── schema/             # JSON schemas (task + event)
├── examples/           # Reference payloads
├── ocs/
│   ├── pending/        # OC proposals awaiting review
│   ├── approved/       # Approved OCs (bridge to tasks)
│   └── denied/         # Denied OCs
└── scripts/            # Node.js worker (Cluster A side)
```

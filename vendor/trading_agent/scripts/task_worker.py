#!/usr/bin/env python3
"""
Cluster B (Claude Code) task worker.

Reads/writes to the coordination bus in the Codex repo.
Mirrors the Node.js task_worker.js protocol exactly.

Usage:
    python3 scripts/task_worker.py list                         # show pending tasks
    python3 scripts/task_worker.py claim                        # claim next pending task
    python3 scripts/task_worker.py claim <task_id>              # claim specific task
    python3 scripts/task_worker.py complete <task_id> "summary" # complete a task
    python3 scripts/task_worker.py complete <task_id> "summary" "artifact1,artifact2"
    python3 scripts/task_worker.py block <task_id> "reason"     # block a task
    python3 scripts/task_worker.py status                       # dashboard: counts + recent events
    python3 scripts/task_worker.py create "title" "description" "bucket" "P1" "criteria1;criteria2"
"""

import json
import os
import random
import string
import sys
from datetime import datetime, timezone
from pathlib import Path

# --- Configuration ---
# Codex repo coordination directory
CODEX_COORDINATION = Path(
    os.environ.get(
        "COORDINATION_DIR",
        "/Users/thom/Documents/Personal/Codex Projects/Trading Agent Codex/coordination",
    )
)

TASKS = CODEX_COORDINATION / "tasks"
EVENTS = CODEX_COORDINATION / "events"
PENDING = TASKS / "pending"
IN_PROGRESS = TASKS / "in_progress"
DONE = TASKS / "done"
BLOCKED = TASKS / "blocked"

ORIGIN = "cluster_b"

VALID_BUCKETS = [
    "Research",
    "Strategy Design",
    "Backtesting",
    "Risk Modeling",
    "Execution Logic",
    "Monitoring",
    "Capital Allocation",
    "Post Trade Review",
]


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ts_compact():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def rand_suffix(n=6):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def ensure_dirs():
    for d in [PENDING, IN_PROGRESS, DONE, BLOCKED, EVENTS]:
        d.mkdir(parents=True, exist_ok=True)


def read_json(path):
    with open(path) as f:
        return json.load(f)


def write_json(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)
        f.write("\n")


def emit_event(event_type, task_id, payload):
    event = {
        "event_id": f"{ts_compact()}_{rand_suffix()}",
        "ts": now_iso(),
        "event_type": event_type,
        "task_id": task_id,
        "origin_cluster": ORIGIN,
        "payload": payload,
    }
    filename = f"{ts_compact()}__{event_type}__{task_id}.json"
    write_json(EVENTS / filename, event)


def pending_files():
    return sorted(f for f in PENDING.iterdir() if f.suffix == ".json")


def in_progress_files():
    return sorted(f for f in IN_PROGRESS.iterdir() if f.suffix == ".json")


def find_task_in_dir(directory, task_id):
    for f in directory.iterdir():
        if f.suffix == ".json" and task_id in f.name:
            return f
    # Also check inside the file for matching task_id
    for f in directory.iterdir():
        if f.suffix != ".json":
            continue
        try:
            data = read_json(f)
            if data.get("task_id") == task_id:
                return f
        except (json.JSONDecodeError, KeyError):
            continue
    return None


# --- Commands ---


def cmd_list():
    files = pending_files()
    if not files:
        print("No pending tasks.")
        return
    print(f"\n{'='*60}")
    print(f"  PENDING TASKS ({len(files)})")
    print(f"{'='*60}")
    for f in files:
        task = read_json(f)
        priority = task.get("priority", "?")
        bucket = task.get("bucket", "?")
        title = task.get("title", "?")
        task_id = task.get("task_id", f.stem)
        print(f"\n  [{priority}] {title}")
        print(f"       id: {task_id}")
        print(f"   bucket: {bucket}")
        criteria = task.get("acceptance_criteria", [])
        if criteria:
            print(f" criteria: {'; '.join(criteria)}")
    print()


def cmd_claim(specific_task_id=None):
    files = pending_files()
    if not files:
        print("No pending tasks.")
        return

    target = None
    if specific_task_id:
        target = find_task_in_dir(PENDING, specific_task_id)
        if not target:
            print(f"Task {specific_task_id} not found in pending/")
            return
    else:
        target = files[0]

    task = read_json(target)
    task["status"] = "in_progress"
    task["updated_at"] = now_iso()
    task["owner_cluster"] = ORIGIN

    write_json(target, task)
    dest = IN_PROGRESS / target.name
    target.rename(dest)

    emit_event("task_claimed", task["task_id"], {"file": target.name})
    print(f"Claimed: {task['task_id']} — {task['title']}")
    print(f"  Moved to: in_progress/{target.name}")


def cmd_complete(task_id, summary, artifacts_csv=None):
    f = find_task_in_dir(IN_PROGRESS, task_id)
    if not f:
        print(f"Task {task_id} not found in in_progress/")
        return

    task = read_json(f)
    task["status"] = "done"
    task["updated_at"] = now_iso()
    task["result_summary"] = summary
    task["result_artifacts"] = (
        [a.strip() for a in artifacts_csv.split(",") if a.strip()]
        if artifacts_csv
        else []
    )
    task["handoff_to"] = "cluster_a"

    write_json(f, task)
    dest = DONE / f.name
    f.rename(dest)

    emit_event(
        "task_completed",
        task["task_id"],
        {"summary": task["result_summary"], "artifacts": task["result_artifacts"]},
    )
    print(f"Completed: {task_id}")


def cmd_block(task_id, reason):
    f = find_task_in_dir(IN_PROGRESS, task_id)
    if not f:
        print(f"Task {task_id} not found in in_progress/")
        return

    task = read_json(f)
    task["status"] = "blocked"
    task["updated_at"] = now_iso()
    task["blocker_reason"] = reason
    task["handoff_to"] = "cluster_a"

    write_json(f, task)
    dest = BLOCKED / f.name
    f.rename(dest)

    emit_event("task_blocked", task["task_id"], {"reason": reason})
    print(f"Blocked: {task_id} — {reason}")


def cmd_create(title, description, bucket, priority="P2", criteria_str=""):
    if bucket not in VALID_BUCKETS:
        print(f"Invalid bucket: {bucket}")
        print(f"Valid: {', '.join(VALID_BUCKETS)}")
        return

    if priority not in ("P1", "P2", "P3"):
        print(f"Invalid priority: {priority} (use P1/P2/P3)")
        return

    task_id = f"task_{ts_compact()}_{rand_suffix(4)}"
    criteria = [c.strip() for c in criteria_str.split(";") if c.strip()] if criteria_str else [title]

    task = {
        "task_id": task_id,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": ORIGIN,
        "owner_cluster": "cluster_a",
        "status": "pending",
        "priority": priority,
        "bucket": bucket,
        "title": title,
        "description": description,
        "acceptance_criteria": criteria,
        "handoff_to": "cluster_a",
    }

    filename = f"{ts_compact()}__{task_id}.json"
    write_json(PENDING / filename, task)
    emit_event("task_created", task_id, {"title": title, "bucket": bucket})
    print(f"Created: {task_id} — {title}")
    print(f"  File: pending/{filename}")
    print(f"  Handoff: cluster_a (GPT PM will pick up)")


def cmd_status():
    pending = list(PENDING.glob("*.json"))
    in_prog = list(IN_PROGRESS.glob("*.json"))
    done = list(DONE.glob("*.json"))
    blocked = list(BLOCKED.glob("*.json"))
    events = sorted(EVENTS.glob("*.json"), key=lambda f: f.name, reverse=True)

    print(f"\n{'='*60}")
    print(f"  COORDINATION DASHBOARD")
    print(f"{'='*60}")
    print(f"  Pending:     {len(pending)}")
    print(f"  In Progress: {len(in_prog)}")
    print(f"  Done:        {len(done)}")
    print(f"  Blocked:     {len(blocked)}")
    print(f"  Events:      {len(events)}")

    if in_prog:
        print(f"\n  --- In Progress ---")
        for f in in_prog:
            task = read_json(f)
            print(f"  [{task.get('priority','?')}] {task.get('title','?')} ({task.get('task_id','?')})")

    if blocked:
        print(f"\n  --- Blocked ---")
        for f in blocked:
            task = read_json(f)
            print(f"  [{task.get('priority','?')}] {task.get('title','?')}")
            print(f"    Reason: {task.get('blocker_reason','?')}")

    if events[:5]:
        print(f"\n  --- Recent Events (last 5) ---")
        for f in events[:5]:
            ev = read_json(f)
            print(f"  {ev.get('ts','')} | {ev.get('event_type','')} | {ev.get('task_id','')}")
    print()


def usage():
    print(__doc__)


def main():
    ensure_dirs()
    args = sys.argv[1:]

    if not args:
        usage()
        sys.exit(1)

    cmd = args[0]

    if cmd == "list":
        cmd_list()
    elif cmd == "claim":
        cmd_claim(args[1] if len(args) > 1 else None)
    elif cmd == "complete":
        if len(args) < 3:
            print("Usage: complete <task_id> \"summary\" [artifacts_csv]")
            sys.exit(1)
        cmd_complete(args[1], args[2], args[3] if len(args) > 3 else None)
    elif cmd == "block":
        if len(args) < 3:
            print("Usage: block <task_id> \"reason\"")
            sys.exit(1)
        cmd_block(args[1], args[2])
    elif cmd == "create":
        if len(args) < 4:
            print('Usage: create "title" "description" "bucket" [priority] [criteria1;criteria2]')
            sys.exit(1)
        cmd_create(
            args[1],
            args[2],
            args[3],
            args[4] if len(args) > 4 else "P2",
            args[5] if len(args) > 5 else "",
        )
    elif cmd == "status":
        cmd_status()
    else:
        usage()
        sys.exit(1)


if __name__ == "__main__":
    main()

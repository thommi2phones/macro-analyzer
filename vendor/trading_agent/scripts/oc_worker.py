#!/usr/bin/env python3
"""
Cluster B (Claude Code) OC worker.

Manages Operational Change proposals and bridges approved OCs into execution tasks.
Reads/writes to the coordination bus in the Codex repo.

Usage:
    python3 scripts/oc_worker.py list                              # show pending OCs
    python3 scripts/oc_worker.py show <oc_id>                      # show full OC details
    python3 scripts/oc_worker.py approve <oc_id> "reason"          # approve an OC
    python3 scripts/oc_worker.py deny <oc_id> "reason"             # deny an OC
    python3 scripts/oc_worker.py bridge                            # convert approved OCs -> tasks
    python3 scripts/oc_worker.py generate                          # generate OCs from trade_history
    python3 scripts/oc_worker.py status                            # dashboard
"""

import json
import os
import random
import string
import sys
from datetime import datetime, timezone
from pathlib import Path

# --- Configuration ---
CODEX_COORDINATION = Path(
    os.environ.get(
        "COORDINATION_DIR",
        "/Users/thom/Documents/Personal/Codex Projects/Trading Agent Codex/coordination",
    )
)

OCS = CODEX_COORDINATION / "ocs"
OC_PENDING = OCS / "pending"
OC_APPROVED = OCS / "approved"
OC_DENIED = OCS / "denied"

TASKS_PENDING = CODEX_COORDINATION / "tasks" / "pending"
EVENTS = CODEX_COORDINATION / "events"

TRADE_HISTORY = Path(
    os.environ.get(
        "TRADE_HISTORY",
        "/Users/thom/Documents/Personal/Code Projects/trading_agent/data/trade_history.json",
    )
)

ORIGIN = "cluster_b"


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ts_compact():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def rand_suffix(n=6):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def ensure_dirs():
    for d in [OC_PENDING, OC_APPROVED, OC_DENIED, TASKS_PENDING, EVENTS]:
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


def find_oc_in_dir(directory, oc_id):
    for f in directory.iterdir():
        if f.suffix != ".json":
            continue
        try:
            data = read_json(f)
            if data.get("oc_id") == oc_id:
                return f, data
        except (json.JSONDecodeError, KeyError):
            continue
    return None, None


def pending_ocs():
    results = []
    for f in sorted(OC_PENDING.iterdir()):
        if f.suffix != ".json":
            continue
        try:
            results.append((f, read_json(f)))
        except (json.JSONDecodeError, KeyError):
            continue
    return results


def approved_ocs():
    results = []
    for f in sorted(OC_APPROVED.iterdir()):
        if f.suffix != ".json":
            continue
        try:
            data = read_json(f)
            results.append((f, data))
        except (json.JSONDecodeError, KeyError):
            continue
    return results


# --- Commands ---


def cmd_list():
    ocs = pending_ocs()
    if not ocs:
        print("No pending OCs.")
        return
    print(f"\n{'='*60}")
    print(f"  PENDING OCs ({len(ocs)})")
    print(f"{'='*60}")
    for _, oc in ocs:
        risk = oc.get("risk", "?")
        title = oc.get("title", "?")
        oc_id = oc.get("oc_id", "?")
        print(f"\n  [{risk.upper()}] {title}")
        print(f"     id: {oc_id}")
        print(f"  trigger: {oc.get('trigger', '?')}")
    print()


def cmd_show(oc_id):
    for directory in [OC_PENDING, OC_APPROVED, OC_DENIED]:
        f, data = find_oc_in_dir(directory, oc_id)
        if data:
            location = directory.name
            print(f"\n{'='*60}")
            print(f"  OC: {data['title']} [{location}]")
            print(f"{'='*60}")
            print(f"        ID: {data['oc_id']}")
            print(f"    Status: {data['status']}")
            print(f"      Risk: {data.get('risk', '?')}")
            print(f"   Problem: {data.get('problem', '?')}")
            print(f"   Trigger: {data.get('trigger', '?')}")
            print(f"    Change: {data.get('proposed_change', '?')}")
            print(f"    Impact: {data.get('expected_impact', '?')}")
            print(f"  Rollback: {data.get('rollback_plan', '?')}")
            criteria = data.get("acceptance_criteria", [])
            if criteria:
                print(f"  Criteria:")
                for c in criteria:
                    print(f"    - {c}")
            note = data.get("review_note", "")
            if note:
                print(f"      Note: {note}")
            print()
            return
    print(f"OC {oc_id} not found.")


def cmd_approve(oc_id, reason):
    f, data = find_oc_in_dir(OC_PENDING, oc_id)
    if not data:
        print(f"OC {oc_id} not found in pending/")
        return

    data["status"] = "approved"
    data["review_note"] = reason
    write_json(f, data)
    dest = OC_APPROVED / f.name
    f.rename(dest)
    print(f"APPROVED: {oc_id} — {data['title']}")


def cmd_deny(oc_id, reason):
    f, data = find_oc_in_dir(OC_PENDING, oc_id)
    if not data:
        print(f"OC {oc_id} not found in pending/")
        return

    data["status"] = "denied"
    data["review_note"] = reason
    write_json(f, data)
    dest = OC_DENIED / f.name
    f.rename(dest)
    print(f"DENIED: {oc_id} — {data['title']}")


def cmd_bridge():
    """Convert approved OCs into execution tasks."""
    ocs = approved_ocs()
    if not ocs:
        print("No approved OCs to bridge.")
        return

    # Check which OCs already have tasks (by looking at existing task descriptions)
    existing_tasks = set()
    for f in TASKS_PENDING.iterdir():
        if f.suffix != ".json":
            continue
        try:
            task = read_json(f)
            desc = task.get("description", "")
            if desc.startswith("OC:"):
                existing_tasks.add(desc.split("OC:")[1].strip().split(" ")[0])
        except (json.JSONDecodeError, KeyError):
            continue

    created = 0
    for _, oc in ocs:
        oc_id = oc["oc_id"]
        if oc_id in existing_tasks:
            continue

        task_id = f"task_{ts_compact()}_{rand_suffix(4)}"
        task = {
            "task_id": task_id,
            "parent_task_id": oc_id,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "created_by": ORIGIN,
            "owner_cluster": "cluster_b",
            "status": "pending",
            "priority": "P1" if oc.get("risk") == "high" else "P2",
            "bucket": _infer_bucket(oc),
            "title": f"Execute OC: {oc['title']}",
            "description": f"OC:{oc_id} — {oc.get('proposed_change', '')}",
            "context": [
                f"Problem: {oc.get('problem', '')}",
                f"Expected impact: {oc.get('expected_impact', '')}",
                f"Rollback: {oc.get('rollback_plan', '')}",
            ],
            "acceptance_criteria": oc.get("acceptance_criteria", []),
            "handoff_to": "none",
        }

        filename = f"{ts_compact()}__{task_id}.json"
        write_json(TASKS_PENDING / filename, task)
        emit_event("task_created", task_id, {
            "title": task["title"],
            "source_oc": oc_id,
            "bucket": task["bucket"],
        })
        print(f"Created task {task_id} from OC {oc_id}")
        created += 1

    if created:
        print(f"\n{created} task(s) created from approved OCs.")
    else:
        print("All approved OCs already have corresponding tasks.")


def _infer_bucket(oc):
    """Map OC content to a coordination bucket."""
    title_lower = oc.get("title", "").lower()
    change_lower = oc.get("proposed_change", "").lower()
    combined = title_lower + " " + change_lower

    if any(w in combined for w in ["confluence", "scoring", "weight", "threshold"]):
        return "Strategy Design"
    if any(w in combined for w in ["backtest", "validation", "sample"]):
        return "Backtesting"
    if any(w in combined for w in ["risk", "position", "sizing", "stop"]):
        return "Risk Modeling"
    if any(w in combined for w in ["execute", "routing", "order", "entry"]):
        return "Execution Logic"
    if any(w in combined for w in ["monitor", "alert", "dashboard"]):
        return "Monitoring"
    if any(w in combined for w in ["metadata", "field", "schema", "mismatch"]):
        return "Research"
    return "Strategy Design"


def cmd_generate():
    """Generate OC proposals from trade_history.json analysis."""
    if not TRADE_HISTORY.exists():
        print(f"trade_history.json not found at {TRADE_HISTORY}")
        return

    trades = read_json(TRADE_HISTORY)
    if not trades:
        print("No trades in history.")
        return

    existing_titles = set()
    for _, oc in pending_ocs():
        existing_titles.add(oc.get("title", ""))

    created = []
    total = len(trades)

    # Analysis 1: Low confluence rate
    low_confluence = sum(
        1 for t in trades
        if t.get("confluence_score") is not None and t["confluence_score"] <= 2
    )
    scored = sum(1 for t in trades if t.get("confluence_score") is not None)
    if scored > 0:
        low_rate = low_confluence / scored
        if low_rate >= 0.5:
            title = "High rate of low-confluence setups in trade history"
            if title not in existing_titles:
                created.append(_build_oc(
                    title,
                    f"{low_confluence}/{scored} trades ({low_rate:.0%}) have confluence <= 2.",
                    "Low confluence rate above 50% in trade history.",
                    "Review and tighten entry criteria; consider requiring confluence >= 3 for execution.",
                    "medium",
                    "Fewer marginal setups reaching execution, higher average R.",
                    ["Average confluence on new setups >= 3", "No drop in capture rate for high-quality setups"],
                    "Revert confluence threshold to previous value.",
                ))

    # Analysis 2: Missing entry/TP data
    missing_entry = sum(1 for t in trades if not t.get("entry_price"))
    missing_tp = sum(1 for t in trades if not t.get("tp_price"))
    missing_rate = max(missing_entry, missing_tp) / total if total else 0
    if missing_rate >= 0.15:
        title = "Incomplete entry/TP data in trade history"
        if title not in existing_titles:
            created.append(_build_oc(
                title,
                f"{missing_entry} missing entries, {missing_tp} missing TPs out of {total} records.",
                "Missing data rate above 15%.",
                "Run review_trades.py --nulls to fill gaps; improve extraction prompt for ambiguous charts.",
                "low",
                "Complete dataset for backtesting and performance analysis.",
                ["Missing entry rate below 5%", "Missing TP rate below 5%"],
                "No rollback needed — data improvement is additive.",
            ))

    # Analysis 3: Setup type concentration
    setup_counts = {}
    for t in trades:
        st = t.get("setup_type", "unknown")
        setup_counts[st] = setup_counts.get(st, 0) + 1
    if setup_counts:
        top_setup = max(setup_counts, key=setup_counts.get)
        top_pct = setup_counts[top_setup] / total
        if top_pct >= 0.35 and top_setup not in ("reference_data", "blank_image"):
            title = f"Over-concentration in {top_setup} setup type"
            if title not in existing_titles:
                created.append(_build_oc(
                    title,
                    f"{top_setup} accounts for {setup_counts[top_setup]}/{total} ({top_pct:.0%}) of all setups.",
                    "Single setup type dominance above 35%.",
                    "Audit whether this reflects genuine edge or pattern-fitting bias. Add diversification tracking.",
                    "low",
                    "Better understanding of setup distribution and potential blind spots.",
                    ["Setup diversity report published", "No single setup type above 30% in next 50 trades"],
                    "No rollback — analysis only.",
                ))

    # Analysis 4: Direction imbalance
    longs = sum(1 for t in trades if t.get("direction") == "long")
    shorts = sum(1 for t in trades if t.get("direction") == "short")
    directional = longs + shorts
    if directional > 20:
        long_pct = longs / directional
        if long_pct >= 0.8 or long_pct <= 0.2:
            bias = "long" if long_pct >= 0.8 else "short"
            title = f"Strong {bias} directional bias in trade history"
            if title not in existing_titles:
                created.append(_build_oc(
                    title,
                    f"{longs} longs vs {shorts} shorts ({long_pct:.0%} long).",
                    f"Directional imbalance above 80% {bias}.",
                    "Review whether bias reflects market conditions or execution blindspot. Add short-side scan rules.",
                    "medium",
                    "More balanced opportunity capture across market regimes.",
                    [f"Long/short ratio between 30-70% over next 50 directional setups"],
                    "No rollback — awareness metric.",
                ))

    if not created:
        print("No new OC proposals generated from trade history analysis.")
        return

    for oc in created:
        filename = f"{ts_compact()}__{oc['oc_id']}.json"
        write_json(OC_PENDING / filename, oc)
        emit_event("task_created", oc["oc_id"], {"title": oc["title"], "source": "trade_history_analysis"})
        print(f"Generated OC: {oc['oc_id']} — {oc['title']}")

    print(f"\n{len(created)} OC(s) generated from trade history.")


def _build_oc(title, problem, trigger, proposed_change, risk, expected_impact, acceptance_criteria, rollback_plan):
    slug = "".join(c if c.isalnum() else "_" for c in title.lower())[:40].strip("_")
    return {
        "oc_id": f"oc_{ts_compact()}_{slug}",
        "created_at": now_iso(),
        "status": "pending",
        "title": title,
        "problem": problem,
        "trigger": trigger,
        "proposed_change": proposed_change,
        "risk": risk,
        "expected_impact": expected_impact,
        "acceptance_criteria": acceptance_criteria,
        "rollback_plan": rollback_plan,
        "approval_required": True,
    }


def cmd_status():
    pending = list(f for f in OC_PENDING.iterdir() if f.suffix == ".json")
    approved = list(f for f in OC_APPROVED.iterdir() if f.suffix == ".json")
    denied = list(f for f in OC_DENIED.iterdir() if f.suffix == ".json")

    print(f"\n{'='*60}")
    print(f"  OC DASHBOARD")
    print(f"{'='*60}")
    print(f"  Pending:  {len(pending)}")
    print(f"  Approved: {len(approved)}")
    print(f"  Denied:   {len(denied)}")

    if pending:
        print(f"\n  --- Pending Review ---")
        for f in sorted(pending):
            oc = read_json(f)
            print(f"  [{oc.get('risk','?').upper()}] {oc.get('title','?')}")
            print(f"       id: {oc.get('oc_id','?')}")
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
    elif cmd == "show":
        if len(args) < 2:
            print("Usage: show <oc_id>")
            sys.exit(1)
        cmd_show(args[1])
    elif cmd == "approve":
        if len(args) < 3:
            print('Usage: approve <oc_id> "reason"')
            sys.exit(1)
        cmd_approve(args[1], args[2])
    elif cmd == "deny":
        if len(args) < 3:
            print('Usage: deny <oc_id> "reason"')
            sys.exit(1)
        cmd_deny(args[1], args[2])
    elif cmd == "bridge":
        cmd_bridge()
    elif cmd == "generate":
        cmd_generate()
    elif cmd == "status":
        cmd_status()
    else:
        usage()
        sys.exit(1)


if __name__ == "__main__":
    main()

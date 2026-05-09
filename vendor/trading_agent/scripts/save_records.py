#!/usr/bin/env python3
"""
Append or upsert trade records into trade_history.json.
Called by Claude Code after analyzing images in-session.

Usage:
    echo '[{"ticker":"XAGUSD",...}]' | python3 scripts/save_records.py
    python3 scripts/save_records.py --file /tmp/batch.json
    python3 scripts/save_records.py --record '{"ticker":"XAGUSD",...}'
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT    = Path(__file__).resolve().parent.parent
HISTORY = ROOT / "data" / "trade_history.json"


def load_existing() -> list[dict]:
    if HISTORY.exists():
        try:
            return json.loads(HISTORY.read_text())
        except Exception:
            return []
    return []


def upsert(existing: list[dict], new_records: list[dict]) -> tuple[list[dict], int, int]:
    """Merge new_records into existing, keyed by image_path basename."""
    by_name = {
        Path(r["image_path"]).name: i
        for i, r in enumerate(existing)
        if r.get("image_path")
    }
    added   = 0
    updated = 0
    result  = list(existing)

    for rec in new_records:
        # Stamp extraction time
        if not rec.get("extracted_at"):
            rec["extracted_at"] = datetime.now().isoformat()
        # Mark as reviewed since Claude Code analyzed it interactively
        rec.setdefault("reviewed", True)

        name = Path(rec.get("image_path", "")).name
        if name and name in by_name:
            result[by_name[name]] = rec
            updated += 1
        else:
            result.append(rec)
            added += 1

    return result, added, updated


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--file",   type=str, help="JSON file containing array of records")
    group.add_argument("--record", type=str, help="Single record as JSON string")
    args = parser.parse_args()

    if args.file:
        new_records = json.loads(Path(args.file).read_text())
    elif args.record:
        new_records = [json.loads(args.record)]
    else:
        # Read from stdin
        raw = sys.stdin.read().strip()
        if not raw:
            print("No input provided.", file=sys.stderr)
            sys.exit(1)
        data = json.loads(raw)
        new_records = data if isinstance(data, list) else [data]

    existing = load_existing()
    merged, added, updated = upsert(existing, new_records)

    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text(json.dumps(merged, indent=2, default=str))

    print(f"✅ Saved: {added} added, {updated} updated → {HISTORY}")
    print(f"   Total records: {len(merged)}")


if __name__ == "__main__":
    main()

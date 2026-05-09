#!/usr/bin/env python3
"""
Print a list of image paths that haven't been analyzed yet.
Claude Code reads this list and processes the images directly — no API needed.

Usage:
    python3 scripts/list_unprocessed.py              # show unprocessed only
    python3 scripts/list_unprocessed.py --all        # show all 352
    python3 scripts/list_unprocessed.py --batch 20   # first N unprocessed
"""

import argparse
import json
import os
from pathlib import Path

ROOT       = Path(__file__).resolve().parent.parent
IMG_DIR    = ROOT / "trade_images"
HISTORY    = ROOT / "data" / "trade_history.json"
CHECKPOINT = ROOT / "data" / "checkpoint.json"

def load_processed_names() -> set[str]:
    names = set()
    for path in [HISTORY, CHECKPOINT]:
        if path.exists():
            try:
                records = json.loads(path.read_text())
                for r in records:
                    if r.get("image_path"):
                        names.add(Path(r["image_path"]).name)
            except Exception:
                pass
    return names

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all",   action="store_true", help="List all 352 images (re-analyze everything)")
    parser.add_argument("--batch", type=int, default=0, help="Limit output to first N images")
    parser.add_argument("--stats", action="store_true", help="Print stats only, no paths")
    args = parser.parse_args()

    exts = {".png", ".jpg", ".jpeg", ".webp"}
    all_images = sorted(p for p in IMG_DIR.iterdir() if p.suffix.lower() in exts)
    processed  = load_processed_names()

    if args.all:
        queue = all_images
    else:
        queue = [p for p in all_images if p.name not in processed]

    total_queue = len(queue)
    if args.batch:
        queue = queue[:args.batch]

    print(f"Total images   : {len(all_images)}")
    print(f"Already done   : {len(processed)}")
    print(f"To process     : {total_queue}")
    if args.batch and args.batch < total_queue:
        print(f"Showing batch  : {len(queue)}")
    print()

    if not args.stats:
        for p in queue:
            print(str(p))

if __name__ == "__main__":
    main()

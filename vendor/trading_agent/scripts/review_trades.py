#!/usr/bin/env python3
"""
Interactive trade review loop.

Opens each chart image on screen, shows what Claude extracted,
and lets you correct any fields. Saves corrections back to trade_history.json.

Usage:
    python3 scripts/review_trades.py                    # review unreviewed records
    python3 scripts/review_trades.py --all              # review all (incl. already reviewed)
    python3 scripts/review_trades.py --nulls            # only records with null entry/exit
    python3 scripts/review_trades.py --ticker XAGUSD    # review specific ticker
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
HISTORY_FILE = ROOT / "data" / "trade_history.json"

# ── Colors ────────────────────────────────────────────────────────────────────
R  = "\033[91m"   # red
G  = "\033[92m"   # green
Y  = "\033[93m"   # yellow
B  = "\033[94m"   # blue
W  = "\033[97m"   # white
DIM = "\033[2m"
RESET = "\033[0m"
BOLD = "\033[1m"


def load_records() -> list[dict]:
    if not HISTORY_FILE.exists():
        print(f"{R}ERROR: {HISTORY_FILE} not found. Run analysis first.{RESET}")
        sys.exit(1)
    with open(HISTORY_FILE) as f:
        return json.load(f)


def save_records(records: list[dict]) -> None:
    with open(HISTORY_FILE, "w") as f:
        json.dump(records, f, indent=2)
    print(f"{DIM}  💾 Saved{RESET}")


def open_image(path: str) -> None:
    """Open image in default viewer (macOS)."""
    if Path(path).exists():
        subprocess.Popen(["open", path])
    else:
        print(f"  {Y}⚠  Image not found: {path}{RESET}")


def prompt(label: str, current, allow_skip: bool = True) -> str:
    """
    Show current value and prompt for new value.
    Returns new value string, or '' to keep current, or 'skip' to skip field.
    """
    cur_str = str(current) if current is not None else f"{DIM}null{RESET}"
    hint = f"[{cur_str}] " if current is not None else f"{DIM}[null]{RESET} "
    suffix = " (Enter=keep, s=skip): " if allow_skip else " (Enter=keep): "
    val = input(f"    {B}{label}{RESET} {hint}{suffix}").strip()
    return val


def parse_float(s: str) -> float | None:
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def parse_bool(s: str) -> bool | None:
    s = s.lower().strip()
    if s in ("y", "yes", "1", "true", "win", "w"):
        return True
    if s in ("n", "no", "0", "false", "loss", "l"):
        return False
    return None


def display_record(idx: int, total: int, r: dict) -> None:
    """Print a formatted summary of the trade record."""
    direction = r.get("direction", "?").upper()
    dir_color = G if direction == "LONG" else R
    win = r.get("win")
    win_str = f"{G}WIN ✓{RESET}" if win is True else f"{R}LOSS ✗{RESET}" if win is False else f"{DIM}?{RESET}"
    reviewed = f" {G}[reviewed]{RESET}" if r.get("reviewed") else ""

    print(f"\n{'─'*60}")
    print(f"  {BOLD}[{idx}/{total}]{RESET}  {W}{r.get('ticker','?')}{RESET}  "
          f"{dir_color}{direction}{RESET}  |  {win_str}{reviewed}")
    print(f"{'─'*60}")

    entry  = r.get("entry_price")
    exit_  = r.get("exit_price")
    sl     = r.get("stop_loss")
    tf     = r.get("timeframe", "?")
    setup  = r.get("setup_type", "?")
    fib    = r.get("fib_levels")
    levels = r.get("key_levels", [])

    print(f"  Timeframe : {tf}")
    print(f"  Setup     : {setup}")
    print(f"  Entry     : {G if entry else Y}{entry if entry else 'null ← WHITE ray'}{RESET}")
    print(f"  TP        : {G if exit_ else Y}{exit_ if exit_ else 'null ← ORANGE ray'}{RESET}")
    print(f"  Stop Loss : {sl if sl else DIM+'null'+RESET}")
    if fib:
        fib_str = "  ".join(f"{k}={v}" for k, v in list(fib.items())[:4])
        print(f"  Fib       : {fib_str}")
    if levels:
        print(f"  Levels    : {levels}")
    notes = r.get("notes", "")
    if notes:
        print(f"  Notes     : {DIM}{notes[:120]}{'...' if len(notes)>120 else ''}{RESET}")
    img = r.get("image_path", "")
    print(f"  Image     : {DIM}{Path(img).name if img else 'none'}{RESET}")


def review_record(r: dict) -> dict:
    """Interactively review and correct a single record. Returns updated record."""
    print(f"\n  {Y}Opening image...{RESET}")
    if r.get("image_path"):
        open_image(r["image_path"])

    print(f"\n  {BOLD}Review fields (Enter = keep current value):{RESET}")
    print(f"  {DIM}Type 's' to skip a field, 'done' to finish review{RESET}\n")

    # ── Ticker ────────────────────────────────────────────────────────────────
    val = prompt("Ticker", r.get("ticker"))
    if val and val.lower() != "s":
        r["ticker"] = val.upper()

    # ── Direction ─────────────────────────────────────────────────────────────
    val = prompt("Direction (long/short)", r.get("direction"))
    if val and val.lower() not in ("s", ""):
        v = val.lower().strip()
        if v in ("l", "long", "buy"):
            r["direction"] = "long"
        elif v in ("s", "short", "sell"):
            r["direction"] = "short"
        else:
            r["direction"] = v

    # ── Entry (white ray) ─────────────────────────────────────────────────────
    val = prompt("Entry price  ← WHITE ray", r.get("entry_price"))
    if val and val.lower() != "s":
        f = parse_float(val)
        if f is not None:
            r["entry_price"] = f

    # ── TP (orange ray) ───────────────────────────────────────────────────────
    val = prompt("TP price     ← ORANGE ray", r.get("exit_price"))
    if val and val.lower() != "s":
        f = parse_float(val)
        if f is not None:
            r["exit_price"] = f

    # ── Stop Loss ─────────────────────────────────────────────────────────────
    val = prompt("Stop loss", r.get("stop_loss"))
    if val and val.lower() != "s":
        f = parse_float(val)
        if f is not None:
            r["stop_loss"] = f

    # ── Timeframe ─────────────────────────────────────────────────────────────
    val = prompt("Timeframe", r.get("timeframe"))
    if val and val.lower() != "s":
        r["timeframe"] = val

    # ── Setup type ────────────────────────────────────────────────────────────
    val = prompt("Setup type", r.get("setup_type"))
    if val and val.lower() != "s":
        r["setup_type"] = val

    # ── Win/Loss ──────────────────────────────────────────────────────────────
    val = prompt("Win? (y/n)", r.get("win"))
    if val and val.lower() != "s":
        b = parse_bool(val)
        if b is not None:
            r["win"] = b

    # ── Notes ─────────────────────────────────────────────────────────────────
    val = prompt("Notes (optional)", r.get("notes"))
    if val and val.lower() != "s":
        r["notes"] = val

    r["reviewed"] = True
    r["reviewed_at"] = datetime.now().isoformat()
    return r


def print_stats(records: list[dict]) -> None:
    total     = len(records)
    reviewed  = sum(1 for r in records if r.get("reviewed"))
    has_entry = sum(1 for r in records if r.get("entry_price") is not None)
    has_tp    = sum(1 for r in records if r.get("exit_price") is not None)
    wins      = sum(1 for r in records if r.get("win") is True)
    losses    = sum(1 for r in records if r.get("win") is False)

    print(f"\n{'═'*60}")
    print(f"  {BOLD}Dataset Summary{RESET}")
    print(f"{'═'*60}")
    print(f"  Total records  : {total}")
    print(f"  Reviewed       : {G}{reviewed}{RESET} / {total}")
    print(f"  Has entry price: {G}{has_entry}{RESET} / {total}")
    print(f"  Has TP price   : {G}{has_tp}{RESET} / {total}")
    print(f"  Wins / Losses  : {G}{wins}{RESET} / {R}{losses}{RESET}  "
          f"(unknown: {total - wins - losses})")
    print(f"{'═'*60}\n")


def main():
    parser = argparse.ArgumentParser(description="Interactive trade history review")
    parser.add_argument("--all",    action="store_true", help="Review all records")
    parser.add_argument("--nulls",  action="store_true", help="Only records missing entry or TP")
    parser.add_argument("--ticker", type=str,            help="Filter by ticker symbol")
    args = parser.parse_args()

    records = load_records()
    print_stats(records)

    # ── Filter ────────────────────────────────────────────────────────────────
    if args.ticker:
        queue = [r for r in records if r.get("ticker","").upper() == args.ticker.upper()]
    elif args.nulls:
        queue = [r for r in records if r.get("entry_price") is None or r.get("exit_price") is None]
    elif args.all:
        queue = records
    else:
        queue = [r for r in records if not r.get("reviewed")]

    if not queue:
        print(f"{G}Nothing to review! Use --all to re-review everything.{RESET}")
        return

    print(f"  {Y}Reviewing {len(queue)} records...{RESET}")
    print(f"  {DIM}Commands: Enter=keep  |  s=skip field  |  Ctrl+C=quit & save{RESET}\n")

    # Build index map for saving back correctly
    record_map = {id(r): i for i, r in enumerate(records)}

    reviewed_count = 0
    try:
        for i, r in enumerate(queue, 1):
            display_record(i, len(queue), r)

            action = input(f"\n  {Y}Review this trade? (y/n/q): {RESET}").strip().lower()
            if action == "q":
                break
            if action != "y":
                print(f"  {DIM}Skipped.{RESET}")
                continue

            updated = review_record(r)
            # Write back to original records list
            orig_idx = record_map.get(id(r))
            if orig_idx is not None:
                records[orig_idx] = updated
            reviewed_count += 1

            # Auto-save every 5 reviews
            if reviewed_count % 5 == 0:
                save_records(records)

    except KeyboardInterrupt:
        print(f"\n\n  {Y}Interrupted — saving progress...{RESET}")

    save_records(records)
    print(f"\n  {G}✓ Reviewed {reviewed_count} trades this session.{RESET}")
    print_stats(records)


if __name__ == "__main__":
    main()

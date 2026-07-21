"""Backfill historical messages from one Telegram channel into the
chart-vision pipeline.

Usage:
  uv run python scripts/backfill_telegram_channel.py \
      --channel feather_hands_trading \
      [--since-days 30] [--limit 200] [--all-history] [--dry-run]

Resolves --channel from settings.telegram_channels (slug → chat_id +
author_display). Calls telegram_poller.backfill() which:
  • paginates through history (newest-first), grouping albums
  • for each new bundle: downloads photos, sha256-dedupes against
    earlier ingests, inserts a documents row with pending_vision=true
  • DM channels skip the user's own outbound messages

The drainer + I3 pipeline pick up from there — no manual handoff.
Re-runs are idempotent: messages already ingested are skipped via
telegram_message_keys lookup.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from macro_positioning.core.settings import settings  # noqa: E402
from macro_positioning.manual.telegram_poller import backfill  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--channel", required=True,
                    help="Channel slug from settings.telegram_channels "
                         "(e.g. feather_hands_trading)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--since-days", type=int, default=None,
                   help="Pull messages from the last N days")
    g.add_argument("--all-history", action="store_true",
                   help="No date cutoff — pull entire channel history")
    ap.add_argument("--limit", type=int, default=None,
                    help="Hard cap on messages to scan (testing)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Count + classify messages without downloading "
                         "media or writing to the DB")
    args = ap.parse_args()

    cfg = settings.telegram_channels.get(args.channel)
    if not cfg:
        print(f"ERROR: unknown channel slug '{args.channel}'. "
              f"Known: {sorted(settings.telegram_channels)}", file=sys.stderr)
        return 2
    if not cfg.get("chat_id"):
        print(f"ERROR: '{args.channel}' has no chat_id configured yet.",
              file=sys.stderr)
        return 2

    print(f"\n=== backfilling {args.channel} (chat_id={cfg['chat_id']}, "
          f"author='{cfg['author_display']}') ===")
    if args.dry_run:
        print("(dry-run — no DB writes, no media downloads)")

    since = None if args.all_history else args.since_days

    stats = asyncio.run(backfill(
        chat_id=cfg["chat_id"],
        slug=args.channel,
        cfg=cfg,
        since_days=since,
        limit=args.limit,
        dry_run=args.dry_run,
    ))

    print("\nresults:")
    for k in sorted(stats):
        print(f"  {k:30s}  {stats[k]}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

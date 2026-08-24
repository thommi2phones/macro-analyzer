"""Twice-daily desk digest — the standing picture, pushed to Telegram.

The alert rules only fire on a *crossing*, by design. That leaves a quiet
week silent even though the desk still has a ranked watchlist worth
reading. This is the complement: three unconditional drops after the
06:00 and 13:00 scoring passes.

  1. live signals — what the tracked voices just said
  2. hero signals — top scored setups, with rails
  3. watchlist    — everything scored, ranked, grouped

Sent as three messages, not one: they get read at different depths, and a
long watchlist must never truncate the hero setups above it.

Run:      python scripts/desk_digest.py
Preview:  python scripts/desk_digest.py --dry-run    (print, send nothing)
Schedule: ~/Library/LaunchAgents/com.macro.desk-digest.plist (06:20, 13:25)
"""
from __future__ import annotations

import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("desk_digest")

from macro_positioning.core.log_redaction import install as _install_redaction  # noqa: E402
_install_redaction()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the messages instead of sending them")
    args = ap.parse_args(argv)

    from macro_positioning.alerts import notify
    from macro_positioning.alerts.digest import build_digest

    sections = build_digest()
    if not sections:
        log.warning("nothing to send — every section was empty")
        return 1

    if args.dry_run:
        for name, msg in sections:
            print(f"\n===== {name} ({len(msg)} chars) =====")
            print(msg)
        return 0

    if not notify.configured():
        log.error("telegram not configured — set MPA_TELEGRAM_BOT_TOKEN "
                  "and MPA_TELEGRAM_ALERT_CHAT_ID")
        return 2

    failed = 0
    for name, msg in sections:
        status = notify.send_text(msg)
        log.info("%s: %s (%d chars)", name, status, len(msg))
        if status != "ok":
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

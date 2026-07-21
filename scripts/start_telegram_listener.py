"""Start the long-running Telegram listener.

Subscribes to NewMessage events on each requested channel and pipes
new posts into the chart-vision pipeline via the same path as backfill.

Usage:
  nohup uv run python scripts/start_telegram_listener.py \
      --channels feather_hands_trading,gem_hunters,og_whales,the_wolf_pack,ari_gold \
      > /tmp/tg-listener.log 2>&1 &
  echo $! > /tmp/tg-listener.pid

The handler buffers multi-photo albums for 2 seconds per grouped_id
before emitting a single document with N attachments. DM channels
(Ari Gold) filter out the user's own outbound messages.

Read-only by construction — see the safety guard in
src/macro_positioning/manual/telegram_poller.py.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from macro_positioning.core.settings import settings  # noqa: E402
from macro_positioning.manual.telegram_poller import listen  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--channels", required=True,
                    help="Comma-separated channel slugs from "
                         "settings.telegram_channels")
    ap.add_argument("--log-level", default="INFO",
                    help="Python log level (default INFO)")
    args = ap.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    slugs = [s.strip() for s in args.channels.split(",") if s.strip()]
    unknown = [s for s in slugs if s not in settings.telegram_channels]
    if unknown:
        print(f"ERROR: unknown channel slugs: {unknown}. Known: "
              f"{sorted(settings.telegram_channels)}", file=sys.stderr)
        return 2

    print(f"starting listener for {len(slugs)} channel(s): {slugs}")
    try:
        asyncio.run(listen(slugs))
    except KeyboardInterrupt:
        print("\nlistener interrupted — clean shutdown")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

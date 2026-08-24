"""Hourly alert watcher — refresh prices, re-score, notify on change.

The full free-ingest job (news, Substack, podcasts, Gmail, insiders,
FRED) runs at 06:00 and 13:00. That cadence is right for narrative data
and wrong for price: a setup that clears its band at 20:00 sat unseen
until the next morning. This job is the fast lane — prices and scoring
only, no LLM calls, no document ingestion.

  1. refresh daily bars for the watchlist (idempotent, replaces today's bar)
  2. re-score with skip_unchanged=True — writes rows only where state moved
  3. evaluate alert rules and deliver

Step 2 is why this is cheap to run hourly: a quiet hour writes zero rows.

Run:      python scripts/alert_watch.py
Test:     python scripts/alert_watch.py --dry-run     (derive, don't send)
          python scripts/alert_watch.py --test-send   (prove the channel)
          python scripts/alert_watch.py --whoami      (find your chat id)
Schedule: ~/Library/LaunchAgents/com.macro.alert-watch.plist
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("alert_watch")

# Providers put credentials in the URL (FRED's api_key query param,
# Telegram's bot token path segment) and httpx logs every request line at
# INFO. launchd sends this job's output to ~/Library/Logs, so without
# this the key lands on disk on every run.
from macro_positioning.core.log_redaction import install as _install_redaction  # noqa: E402
_install_redaction()


def _refresh_prices() -> str:
    """Pull fresh daily bars for everything the scorer will look at.

    `fetch_and_persist` is INSERT OR REPLACE keyed on
    (ticker, observed_at, timeframe), so re-running inside the same day
    overwrites today's partial bar rather than duplicating it — which is
    exactly the intraday refresh this job needs. days=5 keeps the payload
    small; the 200-bar history the scorer wants is already in the table
    from the twice-daily job.
    """
    from macro_positioning.core.settings import settings
    from macro_positioning.prices.fetcher import fetch_and_persist
    from macro_positioning.scoring.watchlist_resolver import resolve_watchlist

    resolved = resolve_watchlist(framework_regime="commodity_led_inflation")
    tickers = {e.ticker for e in resolved.entries}
    tickers |= {"BTC", "ETH", "SOL", "SPX", "NDX", "IWM",
                "GC=F", "SI=F", "HG=F", "GLD", "SLV", "CPER", "DBA"}
    with sqlite3.connect(settings.sqlite_path) as c:
        for (t,) in c.execute(
            "SELECT DISTINCT asset_ticker FROM signals "
            "WHERE extracted_at >= datetime('now','-30 day')"
        ).fetchall():
            if t:
                tickers.add(str(t).upper())
    pr = fetch_and_persist(sorted(tickers), days=5)
    return f"{pr.tickers_with_data}/{pr.tickers_requested} tickers, {pr.bars_persisted} bars"


def _rescore() -> str:
    from macro_positioning.scoring.runner import run_scoring_pass

    # 'scheduled_delta', not 'scheduled': this pass writes only the
    # tickers whose state moved, so it is thin on purpose. The alerts
    # completeness guard measures full snapshots against each other and
    # would otherwise throw every one of these away as a partial run.
    s = run_scoring_pass(pass_kind="scheduled_delta", skip_unchanged=True)
    return (f"{s.persisted} changed, {s.skipped_unchanged} unchanged, "
            f"regime {s.framework_regime}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="derive alerts and print them; send nothing")
    ap.add_argument("--no-rescore", action="store_true",
                    help="evaluate against existing scores only")
    ap.add_argument("--test-send", action="store_true",
                    help="send a test message to the configured channel and exit")
    ap.add_argument("--whoami", action="store_true",
                    help="print chat ids that have messaged the bot, then exit")
    args = ap.parse_args(argv)

    from macro_positioning.alerts import notify
    from macro_positioning.alerts.runner import run_alert_cycle

    if args.whoami:
        try:
            info = notify.resolve_chat_id()
        except notify.NotConfigured as exc:
            log.error("%s", exc)
            return 2
        if not info["chats"]:
            log.error("No chats found. Send your bot a message first, then re-run.")
            return 2
        for chat in info["chats"]:
            print(f"  chat_id={chat['chat_id']}  type={chat['type']}  name={chat['name']}")
        print("\nAdd to .env:  MPA_TELEGRAM_ALERT_CHAT_ID=<chat_id above>")
        return 0

    if args.test_send:
        status = notify.send_test()
        log.info("test send: %s", status)
        return 0 if status == "ok" else 1

    if not args.no_rescore and not args.dry_run:
        for name, fn in (("prices", _refresh_prices), ("rescore", _rescore)):
            t = time.time()
            try:
                log.info("STEP OK  %-8s %.1fs  %s", name, time.time() - t, fn())
            except Exception as exc:  # noqa: BLE001
                # A price-provider hiccup shouldn't stop us evaluating the
                # scores we already have.
                log.exception("STEP FAIL %s", name)
                log.warning("continuing to alert evaluation despite %s failure: %s",
                            name, exc)

    result = run_alert_cycle(dry_run=args.dry_run)
    log.info("alert cycle: %s", json.dumps(result, default=str))
    for a in result.get("alerts", []):
        log.info("  ALERT %-6s %-18s %s", a["severity"], a["rule"], a["title"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""One alert cycle: evaluate → record → deliver.

Scope note. The rules here are entry-side only (crossing into A, crossing
into tier_1, a large one-step gain). Exit-side alerts — stop breached,
score collapse — are a deliberate omission for v1, not an oversight: they
were considered and cut. Adding one means a new rule in rules.py; the
store, cooldown, and delivery path already handle it.
"""

from __future__ import annotations

import logging
import sqlite3

from macro_positioning.alerts import direction_rules, notify, rules, store
from macro_positioning.core.settings import settings

logger = logging.getLogger(__name__)


def run_alert_cycle(*, dry_run: bool = False) -> dict:
    """Evaluate the current scoring state and deliver anything new.

    Delivery covers more than the alerts just derived: any alert inside
    `alert_redelivery_window_hours` without a successful send is retried.
    That is what makes it safe to configure the bot token after the fact —
    alerts fired while the channel was dark still arrive.
    """
    conn = sqlite3.connect(settings.sqlite_path)
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        cooldown = store.recent_fire_keys(
            hours=settings.alert_cooldown_hours, conn=conn
        )
        # Score-band rules say the NUMBER moved; direction rules say the
        # READ moved. Both ride the same cooldown, store and digest.
        fired = rules.evaluate(conn, cooldown_keys=cooldown)
        try:
            fired += direction_rules.evaluate(conn, cooldown_keys=cooldown)
        except Exception:  # noqa: BLE001
            logger.exception("direction rules failed; score alerts still sent")

        if dry_run:
            return {
                "dry_run": True,
                "derived": len(fired),
                "alerts": [
                    {"ticker": a.ticker, "rule": a.rule,
                     "severity": a.severity, "title": a.title}
                    for a in fired
                ],
                "delivered": 0,
                "channel_configured": notify.configured(),
            }

        store.record(fired, conn=conn)

        pending = store.pending_delivery(
            window_hours=settings.alert_redelivery_window_hours,
            channel=notify.CHANNEL,
            conn=conn,
        )
        # One message for the whole cycle, not one per alert. Severity
        # order is already set by rules.evaluate(); pending redeliveries
        # from earlier cycles ride along in the same digest.
        delivered = failed = 0
        if pending:
            status = notify.send_batch(pending)
            for alert in pending:
                store.mark_delivered(
                    alert["alert_id"], notify.CHANNEL, status, conn=conn
                )
            if status == "ok":
                delivered = len(pending)
            else:
                failed = len(pending)

        if failed and not notify.configured():
            logger.warning(
                "%d alert(s) recorded but undelivered — Telegram bot not "
                "configured (MPA_TELEGRAM_BOT_TOKEN / MPA_TELEGRAM_ALERT_CHAT_ID). "
                "They will be retried for the next %dh.",
                failed, settings.alert_redelivery_window_hours,
            )

        return {
            "dry_run": False,
            "derived": len(fired),
            "pending": len(pending),
            "messages_sent": 1 if pending else 0,
            "delivered": delivered,
            "failed": failed,
            "channel_configured": notify.configured(),
            "alerts": [
                {"ticker": a.ticker, "rule": a.rule,
                 "severity": a.severity, "title": a.title}
                for a in fired
            ],
        }
    finally:
        conn.close()

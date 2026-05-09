"""Discord webhook alerts."""

import logging
import os
from datetime import datetime

import requests

from analysis.scanner import Signal

logger = logging.getLogger(__name__)

_COLOR_BUY  = 0x00C853   # green
_COLOR_SELL = 0xFF1744   # red


def send_signal(signal: Signal, webhook_url: str | None = None) -> bool:
    """
    Send a trading signal as a Discord embed.
    Returns True on success.
    """
    url = webhook_url or os.getenv("DISCORD_WEBHOOK_URL")
    if not url:
        logger.warning("DISCORD_WEBHOOK_URL not set – skipping Discord alert")
        return False

    color = _COLOR_BUY if signal.signal == "buy" else _COLOR_SELL
    direction = "🟢 BUY" if signal.signal == "buy" else "🔴 SELL"

    fields = [
        {"name": "Ticker",     "value": f"`{signal.ticker}`",            "inline": True},
        {"name": "Timeframe",  "value": signal.timeframe,                "inline": True},
        {"name": "Price",      "value": f"${signal.price:.4g}",          "inline": True},
        {"name": "Signal",     "value": direction,                        "inline": True},
        {"name": "Confidence", "value": f"{signal.confidence:.0%}",      "inline": True},
    ]
    if signal.rsi is not None:
        fields.append({"name": "RSI", "value": f"{signal.rsi:.1f}", "inline": True})
    if signal.description:
        fields.append({"name": "Rule", "value": signal.description, "inline": False})

    embed = {
        "title": f"{direction}  {signal.ticker}  [{signal.timeframe}]",
        "description": f"**{signal.rule_name}**",
        "color": color,
        "fields": fields,
        "footer": {
            "text": f"Trading Agent  •  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        },
    }

    try:
        resp = requests.post(url, json={"embeds": [embed]}, timeout=10)
        resp.raise_for_status()
        return True
    except requests.RequestException as exc:
        logger.error("Discord alert failed: %s", exc)
        return False


def send_text(message: str, webhook_url: str | None = None) -> bool:
    """Send a plain text message to Discord."""
    url = webhook_url or os.getenv("DISCORD_WEBHOOK_URL")
    if not url:
        return False
    try:
        resp = requests.post(url, json={"content": message}, timeout=10)
        resp.raise_for_status()
        return True
    except requests.RequestException as exc:
        logger.error("Discord message failed: %s", exc)
        return False

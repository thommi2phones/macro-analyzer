"""Email alerts via SMTP."""

import logging
import os
import smtplib
from email.mime.text import MIMEText

from analysis.scanner import Signal

logger = logging.getLogger(__name__)


def send_signal(signal: Signal) -> bool:
    """Send a trading signal via email. Returns True on success."""
    sender   = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_PASSWORD")
    recipient = os.getenv("EMAIL_RECIPIENT")
    host     = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port     = int(os.getenv("SMTP_PORT", "587"))

    if not all([sender, password, recipient]):
        logger.warning("Email credentials not set – skipping email alert")
        return False

    direction = "BUY" if signal.signal == "buy" else "SELL"
    subject = f"[Trading Agent] {direction} {signal.ticker} @ ${signal.price:.4g} [{signal.timeframe}]"

    body = (
        f"Signal  : {direction}\n"
        f"Ticker  : {signal.ticker}\n"
        f"Price   : ${signal.price:.4g}\n"
        f"Timeframe: {signal.timeframe}\n"
        f"Rule    : {signal.rule_name}\n"
        f"Confidence: {signal.confidence:.0%}\n"
    )
    if signal.rsi is not None:
        body += f"RSI     : {signal.rsi:.1f}\n"
    if signal.description:
        body += f"\nDetails : {signal.description}\n"
    body += f"\nTimestamp: {signal.timestamp}"

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = recipient

    try:
        with smtplib.SMTP(host, port) as smtp:
            smtp.starttls()
            smtp.login(sender, password)
            smtp.sendmail(sender, recipient, msg.as_string())
        return True
    except Exception as exc:
        logger.error("Email alert failed: %s", exc)
        return False

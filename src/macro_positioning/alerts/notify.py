"""Delivery — get an alert onto the operator's phone.

Telegram Bot API, not Telethon. The listener process holds an exclusive
lock on `data/telegram.session`; a second process opening it fights that
lock and can wedge ingestion (see CLAUDE.md). A bot is a separate
identity with its own credentials and no shared state, so the alert path
cannot take ingestion down with it.

Setup, once:
  1. Message @BotFather → /newbot → copy the token
  2. Send your new bot any message (bots can't open a chat with you)
  3. `python scripts/alert_watch.py --whoami` prints your chat id
  4. Put both in .env as MPA_TELEGRAM_BOT_TOKEN / MPA_TELEGRAM_ALERT_CHAT_ID
"""

from __future__ import annotations

import contextlib
import html
import logging
from datetime import datetime

import httpx

from macro_positioning.core.settings import settings

logger = logging.getLogger(__name__)

CHANNEL = "telegram"
_API = "https://api.telegram.org/bot{token}/{method}"
_TIMEOUT = 15.0

# Telegram hard-rejects messages over 4096 chars. Ours are ~10 lines, but
# a truncated alert beats a dropped one.
_MAX_LEN = 4000

# Conviction, not alarm. The first cut used 🔴 for the strongest signals,
# which reads backwards to anyone who looks at markets all day: red is
# the colour of a thing going wrong. Green now means highest conviction
# (crossed into A or tier_1 — the tradeable reads), yellow means worth a
# look (cleared the 75 watch band), red means weakest (a big move that
# hasn't cleared a band yet). Direction is carried separately in the
# LONG/SHORT tag, so the dot never has to encode both.
_SEVERITY_DOT = {"high": "🟢", "medium": "🟡", "low": "🔴"}
_DEFAULT_DOT = "🟡"


class NotConfigured(RuntimeError):
    """Raised when the bot token or chat id is missing."""


def _redact(text: str) -> str:
    """Strip the bot token out of anything headed for a log or a return
    value. Belt to `_quiet_httpx`'s braces: httpx puts the request URL
    into exception messages too (HTTPStatusError reads "... for url
    'https://api.telegram.org/bot<TOKEN>/...'"), and those travel up
    through tracebacks and error strings that we do log.
    """
    token = settings.telegram_bot_token
    if token and token in text:
        text = text.replace(token, "<redacted>")
    return text


@contextlib.contextmanager
def _quiet_httpx():
    """Suppress httpx's request log line for the duration of a call.

    The bot token is a *path segment* of every Telegram API URL, so
    httpx's INFO-level "HTTP Request: GET https://.../bot<TOKEN>/..."
    writes the credential verbatim to wherever logging goes — which for
    the launchd job is ~/Library/Logs/macro-alert-watch.err.log, once an
    hour, forever. Scoped to this call rather than set globally at import
    so the rest of the app's logging is untouched.
    """
    log = logging.getLogger("httpx")
    previous = log.level
    log.setLevel(max(previous, logging.WARNING))
    try:
        yield
    finally:
        log.setLevel(previous)


def configured() -> bool:
    return bool(settings.telegram_bot_token and settings.telegram_alert_chat_id)


def _local(iso: str | None) -> datetime | None:
    """Parse an ISO timestamp and convert to the machine's local zone.

    Everything in the DB is UTC; every message is read on a phone in
    local time. Converting at the edge keeps storage unambiguous and the
    notification legible.
    """
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso)).astimezone()
    except (TypeError, ValueError):
        return None


def _when(iso: str | None, *, now: datetime | None = None) -> str:
    """Compact stamp: time-only for today, day + month otherwise.

    "17:07" reads as "just now, this cycle"; "20 Aug 17:07" flags an
    alert that has been sitting undelivered — a real case, since failed
    sends are retried for 24h.
    """
    when = _local(iso)
    if when is None:
        return ""
    now = now or datetime.now().astimezone()
    if when.date() == now.date():
        return when.strftime("%H:%M")
    return when.strftime("%-d %b %H:%M")


def _esc(text: str) -> str:
    """Escape for Telegram's HTML parse mode.

    quote=False on purpose. Python's default also turns ' into &#x27;,
    but Telegram's parser only documents &lt; &gt; &amp; &quot; — anything
    else can reach the phone as literal entity text ("structure
    hasn&#x27;t formed yet"). Apostrophes need no escaping in element
    content, so leaving them alone is both safer and correct.
    """
    return html.escape(str(text), quote=False)


def _format(alert: dict) -> str:
    """HTML-formatted message body.

    Escaped because tickers and setup names are interpolated, and one
    stray '<' would make Telegram reject the whole send.
    """
    siren = _SEVERITY_DOT.get(alert.get("severity"), _DEFAULT_DOT)
    title = _esc(alert.get("title") or "")
    body = _esc(alert.get("body") or "")
    # The title is already the first line of body — drop the duplicate.
    body_lines = body.split("\n")
    if body_lines and body_lines[0] == title:
        body = "\n".join(body_lines[1:]).lstrip("\n")
    # Mirror the digest line's facts so a single alert and a digest row
    # read the same: asset, score move, grade + tier, direction.
    side = alert.get("side")
    facts = []
    if alert.get("score_before") is not None:
        facts.append(f"{alert['score_before']}→{alert['score_after']}")
    if alert.get("grade_after"):
        facts.append(f"{_esc(alert['grade_after'])} · {_esc(alert.get('tier_after') or '')}")
    if side:
        facts.append(f"<b>{_esc(side)}</b>")
    header = f"{siren} <b>{title}</b>"
    if facts:
        header += "\n" + "  ".join(facts)
    # When it fired, and how long the move took to get here. Both matter
    # on a single alert: it may be a redelivery hours after the fact.
    now = datetime.now().astimezone()
    stamps = []
    fired = _when(alert.get("fired_at"), now=now)
    if fired:
        stamps.append(fired)
    span = _when((alert.get("payload") or {}).get("prev_scored_at"), now=now)
    if span:
        stamps.append(f"moved since {span}")
    if stamps:
        header += "\n" + " · ".join(stamps)
    text = f"{header}\n\n{body}"
    return text[:_MAX_LEN]


def _digest_line(alert: dict, *, now: datetime | None = None) -> str:
    """One scannable line: asset · score move · grade+tier · direction.

        🟢 ETH  74→86  A · tier_1  LONG

    Direction is omitted rather than guessed when neither the synthesized
    levels nor the voice consensus is directional — a blank is honest,
    "LONG" by default is not.
    """
    dot = _SEVERITY_DOT.get(alert.get("severity"), _DEFAULT_DOT)
    ticker = _esc(alert.get("ticker") or "")
    before, after = alert.get("score_before"), alert.get("score_after")
    move = f"{before}→{after}" if before is not None else str(after)
    grade = _esc(alert.get("grade_after") or "")
    tier = _esc(alert.get("tier_after") or "")
    side = alert.get("side")
    parts = [f"{dot} <b>{ticker}</b>", move, f"{grade} · {tier}"]
    if side:
        parts.append(f"<b>{_esc(side)}</b>")
    # Stamp only alerts that didn't fire in this cycle — a redelivery
    # after a failed send, or one fired before the bot was configured.
    # Same-cycle alerts are already covered by the header timestamp.
    now = now or datetime.now().astimezone()
    fired = _local(alert.get("fired_at"))
    if fired and (now - fired).total_seconds() > 900:
        parts.append(f"· fired {_when(alert.get('fired_at'), now=now)}")
    return "  ".join(parts)


def _format_digest(alerts: list[dict]) -> str:
    """One message for a whole cycle, containing **every** alert in it.

    Sending per-alert is what kills a notification channel: the 2026-08-20
    pass crossed 14 names at once because the regime modifier flipped, and
    14 buzzes for one cause trains you to swipe them away. So: one message.

    But an earlier cut also truncated at 8 lines with "…and 3 more", which
    hid names the operator specifically wanted to see. At ~50 chars a line,
    Telegram's 4096 limit doesn't bite until ~70 alerts, so that cap was
    solving a problem that didn't exist. Truncation now happens only when
    the message would genuinely be rejected, and drops from the bottom —
    lowest conviction first, since rules.evaluate sorts by it.
    """
    if len(alerts) == 1:
        return _format(alerts[0])

    now = datetime.now().astimezone()
    high = [a for a in alerts if a.get("severity") == "high"]
    head = (
        f"{len(alerts)} setups moved"
        + (f" · {len(high)} crossed a band" if high else "")
    )
    header = [f"🔔 <b>{head}</b>", now.strftime("%a %-d %b · %H:%M"), ""]

    # Full detail for the loudest one — enough to act on without opening
    # anything, while the rest stay one line each.
    lead = (high or alerts)[0]
    body = _esc(lead.get("body") or "")
    detail = [ln for ln in body.split("\n")[1:] if ln.strip()]
    footer: list[str] = []
    if detail:
        footer = ["", f"<b>{_esc(lead.get('ticker') or '')}</b> —"]
        span = _when((lead.get("payload") or {}).get("prev_scored_at"), now=now)
        if span:
            footer.append(f"Moved since {span}")
        footer += detail

    budget = _MAX_LEN - (len("\n".join(header + footer)) + 1)
    body_lines: list[str] = []
    for i, a in enumerate(alerts):
        line = _digest_line(a, now=now)
        remaining = len(alerts) - i
        # Reserve room for the truncation notice only while one is still
        # possible; the final line never needs it.
        reserve = (len(f"…and {remaining} more (message limit)") + 1
                   if remaining > 1 else 0)
        if budget - (len(line) + 1) < reserve:
            body_lines.append(f"…and {remaining} more (message limit)")
            break
        body_lines.append(line)
        budget -= len(line) + 1

    return "\n".join(header + body_lines + footer)[:_MAX_LEN]


def _post(text: str) -> str:
    if not configured():
        return "error: not configured (MPA_TELEGRAM_BOT_TOKEN / MPA_TELEGRAM_ALERT_CHAT_ID)"
    try:
        with _quiet_httpx():
            resp = httpx.post(
                _API.format(token=settings.telegram_bot_token, method="sendMessage"),
                json={
                    "chat_id": settings.telegram_alert_chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=_TIMEOUT,
            )
        if resp.status_code == 200 and resp.json().get("ok"):
            return "ok"
        return _redact(f"error: http {resp.status_code} {resp.text[:200]}")
    except Exception as exc:  # noqa: BLE001
        # exc_info=False deliberately: a traceback frame can carry the
        # request URL, and this line goes to the launchd log.
        logger.warning("telegram send failed: %s", _redact(f"{type(exc).__name__}: {exc}"))
        return _redact(f"error: {type(exc).__name__}: {exc}")


def send(alert: dict) -> str:
    """Deliver one alert. Returns 'ok' or an 'error: ...' string.

    Never raises: a delivery failure must not abort the cycle, because the
    alert is already recorded and the next run retries it.
    """
    return _post(_format(alert))


def send_batch(alerts: list[dict]) -> str:
    """Deliver a cycle's alerts as one message. Same return contract as
    `send`, applied to every alert in the batch.
    """
    if not alerts:
        return "ok"
    return _post(_format_digest(alerts))


def resolve_chat_id() -> dict:
    """Look up the chat id of whoever last messaged the bot.

    Backs `--whoami`, so the one manual setup step doesn't require
    hand-crafting an API URL. getUpdates only returns recent messages, so
    the user has to have messaged the bot first.
    """
    if not settings.telegram_bot_token:
        raise NotConfigured("MPA_TELEGRAM_BOT_TOKEN is not set")
    with _quiet_httpx():
        resp = httpx.get(
            _API.format(token=settings.telegram_bot_token, method="getUpdates"),
            timeout=_TIMEOUT,
        )
    if resp.status_code != 200:
        # Not raise_for_status(): its message embeds the token-bearing URL.
        raise RuntimeError(
            _redact(f"getUpdates failed: http {resp.status_code} {resp.text[:200]}")
        )
    payload = resp.json()
    chats: dict[str, dict] = {}
    for update in payload.get("result", []):
        msg = update.get("message") or update.get("channel_post") or {}
        chat = msg.get("chat") or {}
        if chat.get("id") is not None:
            chats[str(chat["id"])] = {
                "chat_id": chat["id"],
                "type": chat.get("type"),
                "name": chat.get("title") or chat.get("username")
                        or chat.get("first_name"),
            }
    return {"chats": list(chats.values()), "raw_count": len(payload.get("result", []))}


def send_test() -> str:
    """End-to-end check of the configured channel."""
    return send({
        "severity": "medium",
        "title": "Macro Analyzer alerts are wired",
        "body": (
            "Macro Analyzer alerts are wired\n\n"
            "This is the channel that would have told you about ETH on "
            "2026-08-17 and BTC on 2026-08-20.\n\n"
            "You'll hear from it on a grade cross into A or tier_1, or a "
            f"one-step gain of {settings.alert_score_jump}+ points."
        ),
    })

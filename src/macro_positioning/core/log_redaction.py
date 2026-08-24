"""Keep secrets out of the log files.

Several providers put credentials in the URL, and httpx logs every
request line at INFO. The launchd jobs redirect stdout/stderr to
~/Library/Logs/*.log, so an unguarded run writes the key to disk on
every call, forever:

    GET https://api.stlouisfed.org/fred/...&api_key=<KEY>&file_type=json
    GET https://api.telegram.org/bot<TOKEN>/sendMessage

Rather than silence httpx (its request log is genuinely useful for
debugging ingestion), this filter rewrites the record before it is
emitted. Two passes:

  1. Exact values pulled from settings — the strongest match, and it
     catches the credential wherever it appears, URL or not.
  2. A regex over common credential-bearing query parameters, so a
     provider added later is covered before anyone remembers this file.

Filters attach to handlers, so this only affects what gets written; the
values themselves are untouched.
"""

from __future__ import annotations

import logging
import re

# api_key=…, token=…, access_token=…, apikey=…, key=… in a query string.
# Stops at & or # or whitespace so only the value is replaced.
_QUERY_SECRET = re.compile(
    r"(?i)\b(api[-_]?key|access[-_]?token|auth[-_]?token|token|key|secret)"
    r"=([^&#\s\"']+)"
)
# Telegram puts the bot token in the path, not the query string.
_BOT_TOKEN = re.compile(r"/bot\d{6,}:[A-Za-z0-9_-]{20,}")

_PLACEHOLDER = "<redacted>"


def _settings_secrets() -> list[str]:
    """Concrete credential values worth matching verbatim.

    Read lazily and defensively: this filter must never be the reason a
    log line fails to emit.
    """
    try:
        from macro_positioning.core.settings import settings
    except Exception:  # noqa: BLE001
        return []
    candidates = [
        getattr(settings, name, "")
        for name in (
            "fred_api_key", "finnhub_api_key", "anthropic_api_key",
            "anthropic_chatagent_api_key", "gemini_api_key", "auth_token",
            "telegram_bot_token", "telegram_api_hash", "n8n_webhook_url",
        )
    ]
    # Short values would match far too much text to be safe to replace.
    return sorted(
        {str(c) for c in candidates if isinstance(c, str) and len(c) >= 12},
        key=len,
        reverse=True,
    )


def scrub(text: str, secrets: list[str] | None = None) -> str:
    """Redact credentials from one string."""
    if not text:
        return text
    for secret in secrets if secrets is not None else _settings_secrets():
        if secret and secret in text:
            text = text.replace(secret, _PLACEHOLDER)
    text = _BOT_TOKEN.sub("/bot" + _PLACEHOLDER, text)
    return _QUERY_SECRET.sub(lambda m: f"{m.group(1)}={_PLACEHOLDER}", text)


class SecretRedactingFilter(logging.Filter):
    """Rewrite credential-bearing text out of log records."""

    def __init__(self) -> None:
        super().__init__()
        self._secrets = _settings_secrets()

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            # Render first: args are interpolated into the final message,
            # and the credential is usually inside one of them.
            message = record.getMessage()
            scrubbed = scrub(message, self._secrets)
            if scrubbed != message:
                record.msg = scrubbed
                record.args = ()
        except Exception:  # noqa: BLE001
            # A filter that raises drops the record entirely. Losing a log
            # line is worse than the (already best-effort) redaction.
            pass
        return True


def install(logger: logging.Logger | None = None) -> None:
    """Attach the filter to every handler on the root (or given) logger.

    Call after logging.basicConfig(); handlers created later are not
    covered, which is why the scripts call this at the end of setup.
    """
    target = logger or logging.getLogger()
    f = SecretRedactingFilter()
    for handler in target.handlers:
        handler.addFilter(f)

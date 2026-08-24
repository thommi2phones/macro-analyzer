"""Gmail OAuth: check the token, or re-authorize in one command.

Background. The Gmail ingestion step fails roughly weekly with
`invalid_grant`. That is not a bug in the ingest code — Google expires
refresh tokens issued by an OAuth client whose consent screen is still in
**Testing** status, 7 days after issue. Two ways out:

  Permanent — publish the consent screen. Google Cloud Console →
    APIs & Services → OAuth consent screen → "PUBLISH APP". The app stays
    private to you; "in production" here only means the token stops being
    treated as a 7-day trial grant. This ends the weekly chore.

  Meanwhile — re-authorize with this script when prompted. Takes ~20s.

Usage:
    python scripts/gmail_auth.py              # re-authorize (opens a browser)
    python scripts/gmail_auth.py --check      # report health, no browser
    python scripts/gmail_auth.py --check --notify   # …and alert if action needed

`--check` is what the launchd job runs (com.macro.gmail-token-check). It
attempts a silent refresh first, so on a healthy day it renews the access
token and stays quiet; it only notifies when a human is actually needed.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("gmail_auth")

from macro_positioning.core.log_redaction import install as _install_redaction  # noqa: E402
_install_redaction()


_PUBLISH_HINT = (
    "Permanent fix: Google Cloud Console → APIs & Services → OAuth consent "
    "screen → PUBLISH APP. Testing-status clients get 7-day refresh tokens; "
    "publishing stops the weekly expiry. The app stays private to you."
)


def _notify(health) -> None:
    """Push the prompt to Telegram, reusing the alerts channel."""
    from macro_positioning.alerts import notify

    if not notify.configured():
        log.warning("telegram not configured — cannot send the reminder")
        return
    status = notify.send({
        "severity": "medium",
        "title": "Gmail token needs renewing",
        "body": (
            "Gmail token needs renewing\n\n"
            f"{health.message}\n\n"
            "Newsletter ingestion is skipped until this is done; every other "
            "source keeps running.\n\n"
            f"{_PUBLISH_HINT}"
        ),
    })
    log.info("reminder sent: %s", status)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="report token health and exit; never opens a browser")
    ap.add_argument("--notify", action="store_true",
                    help="with --check, send a Telegram reminder if action is needed")
    args = ap.parse_args(argv)

    from macro_positioning.ingestion.personal_gmail import token_health

    if args.check:
        health = token_health()
        log.info("gmail token: %s", json.dumps(health.as_dict()))
        if health.needs_action:
            log.warning("%s", health.message)
            log.warning("%s", _PUBLISH_HINT)
            if args.notify:
                _notify(health)
            return 1
        log.info("%s", health.message)
        return 0

    # Interactive re-auth.
    if not sys.stdin.isatty():
        log.error("Re-authorization needs a browser and a human — run this "
                  "from a terminal, not a scheduled job.")
        return 2

    health = token_health()
    if not health.needs_action:
        log.info("Token is already healthy (%s) — nothing to do.", health.message)
        return 0

    log.info("%s", health.message)
    # MACRO_GMAIL_ALLOW_OAUTH is the interactive escape hatch in
    # personal_gmail.get_credentials, which otherwise refuses to start a
    # browser flow (a hung flow once stalled the whole free layer for 2 days).
    import os
    os.environ["MACRO_GMAIL_ALLOW_OAUTH"] = "1"
    from macro_positioning.ingestion.personal_gmail import get_credentials

    get_credentials()
    after = token_health()
    log.info("re-auth complete — %s", after.message)
    log.info("%s", _PUBLISH_HINT)
    return 0 if not after.needs_action else 1


if __name__ == "__main__":
    sys.exit(main())

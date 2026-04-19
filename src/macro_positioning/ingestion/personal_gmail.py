"""Personal Gmail connector — separate OAuth from any shared project Gmail.

The existing gmail_connector.py is generic / could be any Gmail account.
This module is for THE USER'S PERSONAL ACCOUNT ONLY, with its own
OAuth client credentials, so it can be used independently from any
work/shared Gmail tooling.

Setup required (one-time, manual):
  1. Create a NEW GCP project (or use existing) separate from other projects.
  2. Enable the Gmail API on that project.
  3. Create OAuth 2.0 Client Credentials (type: Desktop app).
  4. Download the credentials JSON, save as data/personal_gmail_credentials.json
  5. First run: the OAuth flow opens a browser for consent. Token is cached.
  6. Subsequent runs: token refresh is automatic.

Env vars (alternative to credentials file):
  MPA_PERSONAL_GMAIL_CLIENT_ID
  MPA_PERSONAL_GMAIL_CLIENT_SECRET
  MPA_PERSONAL_GMAIL_REFRESH_TOKEN

TODO(stream-a):
  - Implement _load_credentials() to read from settings or file
  - Implement get_gmail_service() using google-auth + google-api-python-client
  - Implement fetch_messages(query) returning parsed dicts
  - Wire to gmail_connector's email_to_raw_document() for normalization
  - Add dedup key based on message_id so re-runs don't bloat DB
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from macro_positioning.core.models import RawDocument
from macro_positioning.core.settings import settings
from macro_positioning.ingestion.gmail_connector import (
    NEWSLETTER_SOURCES,
    build_gmail_query,
    email_to_raw_document,
    get_source_for_email,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# OAuth + service builder (stub — Stream A to complete)
# ---------------------------------------------------------------------------

PERSONAL_CREDENTIALS_PATH = Path("data/personal_gmail_credentials.json")


def _load_credentials():
    """Load personal Gmail OAuth credentials.

    Priority:
      1. Env vars (MPA_PERSONAL_GMAIL_CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN)
      2. Credentials file at data/personal_gmail_credentials.json
      3. Token cache at settings.personal_gmail_token_path
    """
    if settings.personal_gmail_client_id and settings.personal_gmail_refresh_token:
        return {
            "source": "env",
            "client_id": settings.personal_gmail_client_id,
            "client_secret": settings.personal_gmail_client_secret,
            "refresh_token": settings.personal_gmail_refresh_token,
        }

    if PERSONAL_CREDENTIALS_PATH.exists():
        data = json.loads(PERSONAL_CREDENTIALS_PATH.read_text())
        return {"source": "file", "raw": data}

    raise RuntimeError(
        "Personal Gmail credentials not configured. "
        "Set MPA_PERSONAL_GMAIL_* env vars OR place OAuth JSON at "
        f"{PERSONAL_CREDENTIALS_PATH}. "
        "See personal_gmail.py docstring for setup."
    )


def get_gmail_service():
    """Build an authenticated Gmail API service object.

    TODO(stream-a): implement using google-auth + googleapiclient.
    Returns: googleapiclient.discovery.Resource
    """
    raise NotImplementedError(
        "Stream A: implement using google-auth OAuth flow. "
        "Scopes: ['https://www.googleapis.com/auth/gmail.readonly']. "
        "Token should cache to settings.personal_gmail_token_path."
    )


# ---------------------------------------------------------------------------
# Fetch newsletters
# ---------------------------------------------------------------------------

def fetch_newsletters(
    days: int = 7,
    sources: list | None = None,
    max_messages: int = 100,
) -> list[RawDocument]:
    """Fetch newsletters from personal Gmail and return RawDocument list.

    Args:
        days: Look-back window
        sources: Specific NewsletterSource list (defaults to all)
        max_messages: Safety cap per run

    TODO(stream-a):
      1. Build query via build_gmail_query(sources, days)
      2. service.users().messages().list(userId='me', q=query).execute()
      3. For each message ID:
         - service.users().messages().get(userId='me', id=msg_id, format='full')
         - Extract headers (From, Subject, Date)
         - Extract HTML body (walk MIME parts)
         - Call email_to_raw_document() to normalize
      4. Dedup by message_id against SQLite documents table
      5. Return list of RawDocument
    """
    raise NotImplementedError("Stream A: implement Gmail message fetch + parse")


def fetch_and_persist(
    days: int = 7,
    max_messages: int = 100,
) -> dict:
    """Fetch, normalize, dedup, and persist newsletters. Returns summary dict.

    TODO(stream-a): wire into SQLiteRepository, return:
      {
        "fetched": int,
        "new_documents": int,
        "duplicates_skipped": int,
        "parse_failures": int,
        "sources": {source_id: count}
      }
    """
    raise NotImplementedError("Stream A: implement persistence path")


# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------

def print_setup_instructions() -> None:
    """Print setup instructions to stdout. For use in CLI / interactive help."""
    print("""
╔══════════════════════════════════════════════════════════════════════╗
║ PERSONAL GMAIL SETUP                                                 ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║ 1. Create a NEW Google Cloud project (or use a personal one that is  ║
║    SEPARATE from any work/shared projects).                          ║
║    → https://console.cloud.google.com/projectcreate                  ║
║                                                                      ║
║ 2. Enable the Gmail API on that project.                             ║
║    → APIs & Services → Library → search "Gmail API" → Enable         ║
║                                                                      ║
║ 3. Configure the OAuth consent screen (External, then add your       ║
║    personal email as a test user).                                   ║
║                                                                      ║
║ 4. Create OAuth 2.0 Client ID credentials (Application type:         ║
║    "Desktop app"). Download the JSON.                                ║
║                                                                      ║
║ 5. Save the JSON to:                                                 ║
║      data/personal_gmail_credentials.json                            ║
║                                                                      ║
║ 6. Run: python -m macro_positioning.cli gmail-setup                  ║
║    This opens a browser for consent and caches a refresh token.      ║
║                                                                      ║
║ 7. Add scope:                                                        ║
║      https://www.googleapis.com/auth/gmail.readonly                  ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
""")

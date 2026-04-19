"""Personal Gmail connector — separate OAuth from shared project Gmail.

Uses the credentials at data/personal_gmail_credentials.json to authenticate
against the user's personal Gmail and fetch financial newsletters.

One-time setup:
  1. Credentials JSON must exist at data/personal_gmail_credentials.json
  2. First run triggers browser-based consent; refresh token cached to
     data/personal_gmail_token.json
  3. Subsequent runs are silent — no browser needed

Scope: readonly access only.
"""

from __future__ import annotations

import base64
import json
import logging
import re
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


SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
PERSONAL_CREDENTIALS_PATH = Path("data/personal_gmail_credentials.json")


# ---------------------------------------------------------------------------
# OAuth + service builder
# ---------------------------------------------------------------------------

def _token_path() -> Path:
    return Path(settings.personal_gmail_token_path or "data/personal_gmail_token.json")


def get_credentials():
    """Load or create OAuth credentials for the personal Gmail account.

    Priority:
      1. Cached refresh token at token_path — silent refresh
      2. If credentials JSON present but no token → browser-based consent flow
      3. Raises RuntimeError if neither is available
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    token_path = _token_path()
    creds = None

    # Cached token?
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except Exception as e:
            logger.warning("Failed to load cached token: %s", e)

    # Valid token?
    if creds and creds.valid:
        return creds

    # Expired but refreshable?
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_credentials(creds)
            return creds
        except Exception as e:
            logger.warning("Token refresh failed: %s", e)
            creds = None

    # No valid credentials — trigger browser consent flow
    if not PERSONAL_CREDENTIALS_PATH.exists():
        raise RuntimeError(
            f"Credentials file not found at {PERSONAL_CREDENTIALS_PATH}. "
            "See print_setup_instructions() for setup walkthrough."
        )

    logger.info("Starting browser OAuth flow (one-time)…")
    flow = InstalledAppFlow.from_client_secrets_file(
        str(PERSONAL_CREDENTIALS_PATH), SCOPES
    )
    creds = flow.run_local_server(port=0)
    _save_credentials(creds)
    logger.info("OAuth complete — token cached to %s", token_path)
    return creds


def _save_credentials(creds) -> None:
    path = _token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(creds.to_json())
    path.chmod(0o600)


def get_gmail_service():
    """Return an authenticated Gmail API service."""
    from googleapiclient.discovery import build

    creds = get_credentials()
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def get_profile() -> dict:
    """Return the authenticated Gmail profile (emailAddress, messagesTotal, etc.)."""
    service = get_gmail_service()
    return service.users().getProfile(userId="me").execute()


# ---------------------------------------------------------------------------
# Message fetching
# ---------------------------------------------------------------------------

def search_messages(query: str, max_messages: int = 50) -> list[dict]:
    """Search Gmail with a query string. Returns list of {id, threadId} stubs."""
    service = get_gmail_service()
    messages: list[dict] = []
    next_page = None
    while len(messages) < max_messages:
        remaining = max_messages - len(messages)
        resp = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=min(remaining, 100),
            pageToken=next_page,
        ).execute()
        messages.extend(resp.get("messages", []) or [])
        next_page = resp.get("nextPageToken")
        if not next_page:
            break
    return messages[:max_messages]


def get_message_full(message_id: str) -> dict:
    """Fetch a Gmail message with full body payload."""
    service = get_gmail_service()
    return service.users().messages().get(
        userId="me",
        id=message_id,
        format="full",
    ).execute()


def _extract_html_body(payload: dict) -> str:
    """Walk the Gmail MIME tree and return the first HTML body found.

    Falls back to plain text if no HTML part is present.
    """
    def decode(data: str) -> str:
        try:
            return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="replace")
        except Exception:
            return ""

    def walk(part: dict) -> tuple[str, str]:
        """Return (html, text) found in this part and its children."""
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data", "")
        html = ""
        text = ""
        if data:
            if mime == "text/html":
                html = decode(data)
            elif mime == "text/plain":
                text = decode(data)
        for child in part.get("parts", []) or []:
            ch_html, ch_text = walk(child)
            html = html or ch_html
            text = text or ch_text
        return html, text

    html, text = walk(payload)
    return html or text


def _header(headers: list, name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


# ---------------------------------------------------------------------------
# Newsletter fetching
# ---------------------------------------------------------------------------

def fetch_newsletters(
    days: int = 7,
    sources: list | None = None,
    max_messages: int = 100,
) -> list[RawDocument]:
    """Fetch newsletters matching configured sources within the look-back window.

    Returns a list of RawDocument objects ready for the pipeline.
    Skips messages we can't confidently attribute to a configured source.
    """
    query = build_gmail_query(sources, days=days)
    logger.info("Searching personal Gmail: %s", query)

    stubs = search_messages(query, max_messages=max_messages)
    logger.info("Found %d matching messages", len(stubs))

    documents: list[RawDocument] = []
    for stub in stubs:
        try:
            msg = get_message_full(stub["id"])
            headers = msg.get("payload", {}).get("headers", []) or []
            subject = _header(headers, "Subject")
            from_hdr = _header(headers, "From")
            date_hdr = _header(headers, "Date")
            body_html = _extract_html_body(msg.get("payload", {}))

            doc = email_to_raw_document(
                message_id=stub["id"],
                subject=subject,
                from_header=from_hdr,
                date_header=date_hdr,
                body_html=body_html,
            )
            if doc:
                documents.append(doc)
        except Exception as e:
            logger.warning("Failed to fetch/parse message %s: %s", stub.get("id"), e)

    logger.info("Parsed %d newsletter RawDocuments", len(documents))
    return documents


def fetch_and_persist(days: int = 7, max_messages: int = 100) -> dict:
    """Fetch + normalize + persist into the SQLite documents table with dedup."""
    from macro_positioning.db.repository import SQLiteRepository
    from macro_positioning.db.schema import initialize_database
    from macro_positioning.ingestion.base import normalize_document

    initialize_database(settings.sqlite_path)
    repo = SQLiteRepository(settings.sqlite_path)

    docs = fetch_newsletters(days=days, max_messages=max_messages)

    new_count = 0
    dup_count = 0
    by_source: dict[str, int] = {}

    for raw in docs:
        normalized = normalize_document(raw)
        try:
            inserted = repo.save_document(normalized)
            if inserted:
                new_count += 1
                by_source[raw.source_id] = by_source.get(raw.source_id, 0) + 1
            else:
                dup_count += 1
        except Exception as e:
            logger.warning("Failed to persist %s: %s", raw.source_id, e)

    return {
        "fetched": len(docs),
        "new_documents": new_count,
        "duplicates_skipped": dup_count,
        "sources": by_source,
    }


# ---------------------------------------------------------------------------
# Diagnostic helpers
# ---------------------------------------------------------------------------

def sanity_check() -> dict:
    """Quick check that OAuth works + show account summary."""
    profile = get_profile()
    return {
        "email": profile.get("emailAddress"),
        "total_messages": profile.get("messagesTotal"),
        "total_threads": profile.get("threadsTotal"),
    }


def list_substack_senders(days: int = 30, max_messages: int = 200) -> dict:
    """Scan recent mail from substack.com and return unique sender counts.

    Useful for discovering new newsletters to add to NEWSLETTER_SOURCES.
    """
    query = f"from:substack.com newer_than:{days}d"
    stubs = search_messages(query, max_messages=max_messages)

    senders: dict[str, dict] = {}
    service = get_gmail_service()

    for stub in stubs:
        msg = service.users().messages().get(
            userId="me", id=stub["id"], format="metadata",
            metadataHeaders=["From", "Subject"],
        ).execute()
        headers = msg.get("payload", {}).get("headers", []) or []
        from_hdr = _header(headers, "From")
        match = re.search(r"<([^>]+)>", from_hdr)
        email_addr = match.group(1).lower() if match else from_hdr.lower().strip()
        if email_addr not in senders:
            source = get_source_for_email(from_hdr)
            senders[email_addr] = {
                "count": 0,
                "known": source.source_id if source else None,
                "display_name": from_hdr.split("<")[0].strip().strip('"'),
                "sample_subject": _header(headers, "Subject"),
            }
        senders[email_addr]["count"] += 1

    return {
        "query": query,
        "total_messages": len(stubs),
        "unique_senders": len(senders),
        "senders": dict(sorted(senders.items(), key=lambda kv: -kv[1]["count"])),
    }


# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------

def print_setup_instructions() -> None:
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
║ 6. First fetch_newsletters() call triggers browser consent.          ║
║                                                                      ║
║ 7. Scope requested:                                                  ║
║      https://www.googleapis.com/auth/gmail.readonly                  ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
""")


def cli_sanity_check() -> None:
    """CLI entry point: verify credentials and show profile."""
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        result = sanity_check()
        print("✓ Personal Gmail OAuth working")
        print(f"  Email: {result['email']}")
        print(f"  Total messages: {result['total_messages']}")
        print(f"  Total threads: {result['total_threads']}")
    except Exception as e:
        print(f"✗ Sanity check failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    cli_sanity_check()

"""Gmail newsletter ingestion connector.

Searches Gmail for financial newsletter emails from configured senders,
parses the HTML body into clean text, and produces RawDocument objects
for the thesis extraction pipeline.

Requires the Gmail MCP tool to be available at runtime (for interactive use)
or a Gmail API OAuth token for automated use. This module provides both:

  1. GmailNewsletterConnector — a SourceConnector that can be registered in
     the ConnectorRegistry for pipeline-driven ingestion.
  2. fetch_newsletters() — a standalone helper that searches Gmail directly
     and returns RawDocument objects ready to feed into the pipeline.

Usage (standalone):
    from macro_positioning.ingestion.gmail_connector import fetch_newsletters
    docs = fetch_newsletters(days=7)
    result = pipeline.run(docs)
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser

from macro_positioning.core.models import RawDocument


# ---------------------------------------------------------------------------
# Newsletter source definitions
# ---------------------------------------------------------------------------

@dataclass
class NewsletterSource:
    """A known financial newsletter that arrives via email."""
    source_id: str
    name: str
    sender_email: str
    sender_domain: str
    author: str | None = None
    market_focus: list[str] = field(default_factory=list)
    priority: str = "secondary"
    content_type: str = "article"
    tags: list[str] = field(default_factory=list)


# The newsletter sources discovered from your Gmail inbox
NEWSLETTER_SOURCES: list[NewsletterSource] = [
    NewsletterSource(
        source_id="macromicro",
        name="MacroMicro.me",
        sender_email="web@mg.macromicro.me",
        sender_domain="macromicro.me",
        author="MacroMicro",
        market_focus=["macro", "rates", "inflation", "geopolitics", "commodities"],
        priority="core",
        tags=["macro", "newsletter"],
    ),
    NewsletterSource(
        source_id="stockunlocked",
        name="Stock Unlocked",
        sender_email="noreply@stockunlocked.com",
        sender_domain="stockunlocked.com",
        author="Stock Unlocked",
        market_focus=["equities", "crypto", "geopolitics"],
        priority="core",
        tags=["equities", "crypto", "newsletter"],
    ),
    NewsletterSource(
        source_id="realvision",
        name="Real Vision",
        sender_email="info@realvision.com",
        sender_domain="realvision.com",
        author="Real Vision",
        market_focus=["macro", "rates", "equities", "commodities", "crypto"],
        priority="core",
        tags=["macro", "newsletter"],
    ),
    NewsletterSource(
        source_id="kaoboy_musings",
        name="Kaoboy Musings",
        sender_email="urbankaoboy@substack.com",
        sender_domain="substack.com",
        author="Michael Kao",
        market_focus=["macro", "commodities", "rates", "geopolitics"],
        priority="core",
        tags=["macro", "commodities", "newsletter"],
    ),
    NewsletterSource(
        source_id="doomberg",
        name="Doomberg",
        sender_email="doomberg@substack.com",
        sender_domain="substack.com",
        author="Doomberg",
        market_focus=["commodities", "energy", "macro"],
        priority="core",
        tags=["energy", "commodities", "newsletter"],
    ),
    NewsletterSource(
        source_id="qtr_fringe",
        name="QTR's Fringe Finance",
        sender_email="quoththeraven@substack.com",
        sender_domain="substack.com",
        author="Quoth the Raven",
        market_focus=["macro", "equities", "contrarian"],
        priority="secondary",
        tags=["macro", "contrarian", "newsletter"],
    ),
    NewsletterSource(
        source_id="bitcoin_layer",
        name="The Bitcoin Layer",
        sender_email="thebitcoinlayer@substack.com",
        sender_domain="substack.com",
        author="The Bitcoin Layer",
        market_focus=["crypto", "macro", "rates"],
        priority="secondary",
        tags=["crypto", "macro", "newsletter"],
    ),
    NewsletterSource(
        source_id="deepvalue_capital",
        name="DeepValue Capital",
        sender_email="deepvaluecapitalbykyler@substack.com",
        sender_domain="substack.com",
        author="Kyler Johnson",
        market_focus=["equities", "value"],
        priority="secondary",
        tags=["equities", "value", "newsletter"],
    ),
    NewsletterSource(
        source_id="hidden_market_gems",
        name="Hidden Market Gems",
        sender_email="sbeautiful@substack.com",
        sender_domain="substack.com",
        author="Hidden Market Gems",
        market_focus=["equities"],
        priority="secondary",
        tags=["equities", "newsletter"],
    ),
    NewsletterSource(
        source_id="timeless_investing",
        name="Timeless Investing Principles",
        sender_email="timelessinvestingprinciples@substack.com",
        sender_domain="substack.com",
        author="The Antifragile Investor",
        market_focus=["equities", "macro"],
        priority="secondary",
        tags=["equities", "investing", "newsletter"],
    ),
]

# Lookup by sender email
_SOURCE_BY_EMAIL: dict[str, NewsletterSource] = {s.sender_email: s for s in NEWSLETTER_SOURCES}

# Lookup by source_id
_SOURCE_BY_ID: dict[str, NewsletterSource] = {s.source_id: s for s in NEWSLETTER_SOURCES}


# ---------------------------------------------------------------------------
# HTML → plain text
# ---------------------------------------------------------------------------

class _HTMLTextExtractor(HTMLParser):
    """Simple HTML to text converter that strips tags and extracts readable content."""

    SKIP_TAGS = frozenset({"script", "style", "head", "meta", "link", "noscript"})

    def __init__(self) -> None:
        super().__init__()
        self._pieces: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        if tag in ("br", "p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "hr"):
            self._pieces.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        if tag in ("p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6"):
            self._pieces.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._pieces.append(data)

    def get_text(self) -> str:
        text = "".join(self._pieces)
        # Collapse whitespace but preserve paragraph breaks
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def html_to_text(html: str) -> str:
    """Convert HTML email body to readable plain text."""
    parser = _HTMLTextExtractor()
    parser.feed(html)
    return parser.get_text()


# ---------------------------------------------------------------------------
# Email → RawDocument conversion
# ---------------------------------------------------------------------------

def _parse_email_date(date_str: str) -> datetime:
    """Parse RFC 2822 email date into a UTC datetime."""
    # Common formats from email headers
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%d %b %Y %H:%M:%S %z",
    ):
        try:
            return datetime.strptime(date_str.strip(), fmt).astimezone(UTC)
        except ValueError:
            continue
    # Fallback: try to extract from internalDate (epoch ms)
    return datetime.now(UTC)


def _extract_sender_email(from_header: str) -> str:
    """Extract the email address from a From header like 'Name <email@domain.com>'."""
    match = re.search(r"<([^>]+)>", from_header)
    return match.group(1).lower() if match else from_header.lower().strip()


def _is_newsletter_content(subject: str) -> bool:
    """Filter out non-content emails (verification codes, welcome messages, payment notices)."""
    skip_patterns = [
        r"verification code",
        r"verify your email",
        r"password recovery",
        r"recurring payment",
        r"you'?re on the .* list",
        r"welcome to",
        r"you'?re almost subscribed",
        r"people you know",
        r"welcome,",
    ]
    subject_lower = subject.lower()
    return not any(re.search(pattern, subject_lower) for pattern in skip_patterns)


def email_to_raw_document(
    message_id: str,
    subject: str,
    from_header: str,
    date_header: str,
    body_html: str,
    source: NewsletterSource | None = None,
) -> RawDocument | None:
    """Convert a Gmail message into a RawDocument for the pipeline.

    Returns None if the email doesn't look like actual newsletter content
    (e.g. welcome emails, verification codes, payment notices).
    """
    if not _is_newsletter_content(subject):
        return None

    sender_email = _extract_sender_email(from_header)

    if source is None:
        source = _SOURCE_BY_EMAIL.get(sender_email)
    if source is None:
        # Try matching by domain
        sender_domain = sender_email.split("@")[-1] if "@" in sender_email else ""
        for s in NEWSLETTER_SOURCES:
            if sender_domain == s.sender_domain or sender_domain.endswith(f".{s.sender_domain}"):
                source = s
                break

    if source is None:
        return None

    plain_text = html_to_text(body_html) if body_html else ""
    if len(plain_text) < 50:
        return None

    published_at = _parse_email_date(date_header)

    return RawDocument(
        source_id=source.source_id,
        title=subject,
        url=f"gmail://message/{message_id}",
        published_at=published_at,
        author=source.author,
        content_type=source.content_type,
        raw_text=plain_text,
        tags=source.tags,
    )


# ---------------------------------------------------------------------------
# Gmail search query builder
# ---------------------------------------------------------------------------

def build_gmail_query(
    sources: list[NewsletterSource] | None = None,
    days: int = 7,
) -> str:
    """Build a Gmail search query for all configured newsletter sources.

    Args:
        sources: Specific sources to search for. Defaults to all NEWSLETTER_SOURCES.
        days: Number of days to look back. Defaults to 7.
    """
    sources = sources or NEWSLETTER_SOURCES
    sender_clauses = " OR ".join(f"from:{s.sender_email}" for s in sources)
    return f"({sender_clauses}) newer_than:{days}d"


def get_source_for_email(from_header: str) -> NewsletterSource | None:
    """Look up the newsletter source for a given From header."""
    sender_email = _extract_sender_email(from_header)
    source = _SOURCE_BY_EMAIL.get(sender_email)
    if source:
        return source
    sender_domain = sender_email.split("@")[-1] if "@" in sender_email else ""
    for s in NEWSLETTER_SOURCES:
        if sender_domain == s.sender_domain or sender_domain.endswith(f".{s.sender_domain}"):
            return s
    return None

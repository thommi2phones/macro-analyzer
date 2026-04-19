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
    notes: str = ""   # free-form note, e.g. "mostly video links"


# The newsletter sources discovered from your Gmail inbox
NEWSLETTER_SOURCES: list[NewsletterSource] = [
    # ═══ CORE — highest trust / primary signal ═══
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
        source_id="deepvalue_capital",
        name="DeepValue Capital",
        sender_email="deepvaluecapitalbykyler@substack.com",
        sender_domain="substack.com",
        author="Kyler Johnson",
        market_focus=["equities", "value"],
        priority="core",
        tags=["equities", "value", "newsletter"],
    ),
    NewsletterSource(
        source_id="arch_public",
        name="Arch Public",
        sender_email="send@archpublic.com",
        sender_domain="archpublic.com",
        author="Arch Public",
        market_focus=["crypto", "macro"],
        priority="core",
        tags=["crypto", "macro", "newsletter"],
    ),
    NewsletterSource(
        source_id="blockworks",
        name="Blockworks (The Breakdown)",
        sender_email="newsletter@blockworks.com",
        sender_domain="blockworks.com",
        author="Blockworks",
        market_focus=["crypto", "macro", "digital_assets"],
        priority="core",
        tags=["crypto", "macro", "newsletter"],
    ),

    # ═══ SECONDARY — trusted but lower weight ═══
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
    NewsletterSource(
        source_id="capital_flows",
        name="Capital Flows",
        sender_email="capitalflows@substack.com",
        sender_domain="substack.com",
        author="Capital Flows",
        market_focus=["macro", "rates", "fx", "liquidity"],
        priority="secondary",
        tags=["macro", "liquidity", "newsletter"],
    ),
    NewsletterSource(
        source_id="stock_analysis_compilation",
        name="Stock Analysis Compilation",
        sender_email="stockanalysiscompilation@substack.com",
        sender_domain="substack.com",
        author="Stock Analysis Compilation",
        market_focus=["equities"],
        priority="secondary",
        tags=["equities", "newsletter"],
    ),
    NewsletterSource(
        source_id="weekly_wizdom",
        name="Weekly Wizdom",
        sender_email="weeklywizdom@weeklywizdom.com",
        sender_domain="weeklywizdom.com",
        author="Weekly Wizdom",
        market_focus=["crypto", "trade_ideas"],
        priority="secondary",
        tags=["crypto", "trade_ideas", "newsletter"],
    ),
    NewsletterSource(
        source_id="morning_brew",
        name="Morning Brew",
        sender_email="crew@morningbrew.com",
        sender_domain="morningbrew.com",
        author="Morning Brew",
        market_focus=["macro", "equities", "general_business"],
        priority="secondary",
        tags=["macro", "daily", "newsletter"],
    ),
    NewsletterSource(
        source_id="finimize",
        name="Finimize Daily",
        sender_email="hello@finimize.com",
        sender_domain="finimize.com",
        author="Finimize",
        market_focus=["macro", "equities", "crypto"],
        priority="secondary",
        tags=["macro", "daily", "newsletter"],
    ),
    NewsletterSource(
        source_id="elliott_wave",
        name="Elliott Wave Market Wrap",
        sender_email="customercare@surf.elliottwave.com",
        sender_domain="surf.elliottwave.com",
        author="Elliott Wave International",
        market_focus=["equities", "technical_analysis"],
        priority="secondary",
        tags=["technical", "newsletter"],
    ),

    # ═══ EXPERIMENTAL — unproven, may produce noise ═══
    NewsletterSource(
        source_id="wallstreet_io",
        name="Wallstreet.io",
        sender_email="micah@em.wallstreet.io",
        sender_domain="em.wallstreet.io",
        author="Micah @ Wallstreet.io",
        market_focus=["equities", "trading_frameworks"],
        priority="experimental",
        tags=["equities", "framework", "newsletter", "video_content"],
        notes="Most emails contain link to video analysis. Text body is brief — "
              "consider transcribing linked videos in a future iteration.",
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
    """Convert HTML email body to readable plain text.

    Uses BeautifulSoup for reliable parsing of modern email HTML (the
    stdlib HTMLParser silently fails on many newsletter templates).
    Falls back to the stdlib parser if BS4 is unavailable.
    Strips common invisible filler chars used by Substack etc. as
    anti-preview padding (nbsp runs, zero-width joiners, soft hyphens).
    """
    if not html:
        return ""

    # Preferred path: BeautifulSoup
    try:
        from bs4 import BeautifulSoup  # type: ignore

        soup = BeautifulSoup(html, "html.parser")
        # Remove noise elements entirely
        for tag in soup(["script", "style", "head", "meta", "link", "noscript"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)
    except ImportError:
        parser = _HTMLTextExtractor()
        parser.feed(html)
        text = parser.get_text()

    # Strip invisible filler characters (Substack, Beehiiv, etc. pad
    # preview text with these so Gmail preview looks cleaner)
    _INVISIBLE = (
        "\u00a0",  # nbsp
        "\u2007",  # figure space
        "\u200b",  # zero-width space
        "\u200c",  # zero-width non-joiner
        "\u200d",  # zero-width joiner
        "\u2060",  # word joiner
        "\u00ad",  # soft hyphen
        "\u034f",  # combining grapheme joiner
        "\ufeff",  # BOM / zero-width no-break space
    )
    for ch in _INVISIBLE:
        text = text.replace(ch, " ")

    # Collapse whitespace runs but preserve paragraph breaks
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]*\n\s*", "\n\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


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
    """Look up the newsletter source for a given From header.

    Priority:
      1. Exact email match (e.g. 'doomberg@substack.com' → doomberg)
      2. Domain match, but ONLY if the domain is unique to one source.
         Shared domains like substack.com require an exact email match —
         otherwise every unknown substack would collide onto the first one.
    """
    sender_email = _extract_sender_email(from_header)
    source = _SOURCE_BY_EMAIL.get(sender_email)
    if source:
        return source

    sender_domain = sender_email.split("@")[-1] if "@" in sender_email else ""
    if not sender_domain:
        return None

    # Count how many sources use this exact domain
    matching = [s for s in NEWSLETTER_SOURCES if s.sender_domain == sender_domain]
    if len(matching) == 1:
        return matching[0]
    return None

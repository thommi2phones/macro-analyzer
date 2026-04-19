"""Tests for the Gmail newsletter ingestion connector."""

from macro_positioning.ingestion.gmail_connector import (
    NEWSLETTER_SOURCES,
    _extract_sender_email,
    _is_newsletter_content,
    build_gmail_query,
    email_to_raw_document,
    get_source_for_email,
    html_to_text,
)


class TestHTMLToText:
    def test_strips_tags(self):
        html = "<p>Hello <b>world</b></p>"
        text = html_to_text(html)
        assert "Hello" in text
        assert "world" in text
        assert "<" not in text

    def test_strips_scripts_and_styles(self):
        html = "<style>body{color:red}</style><script>alert(1)</script><p>Content</p>"
        text = html_to_text(html)
        assert "Content" in text
        assert "color" not in text
        assert "alert" not in text

    def test_preserves_paragraph_breaks(self):
        html = "<p>First</p><p>Second</p>"
        text = html_to_text(html)
        assert "First" in text
        assert "Second" in text

    def test_handles_list_items(self):
        html = "<ul><li>One</li><li>Two</li></ul>"
        text = html_to_text(html)
        assert "One" in text
        assert "Two" in text


class TestExtractSenderEmail:
    def test_extracts_from_angle_brackets(self):
        assert _extract_sender_email("MacroMicro <web@mg.macromicro.me>") == "web@mg.macromicro.me"

    def test_handles_plain_email(self):
        assert _extract_sender_email("test@example.com") == "test@example.com"

    def test_handles_quoted_name(self):
        assert _extract_sender_email('"QTR\'s Fringe Finance" <quoththeraven@substack.com>') == "quoththeraven@substack.com"


class TestIsNewsletterContent:
    def test_passes_real_content(self):
        assert _is_newsletter_content("Energy Inflation in the US-Iran Conflict")

    def test_filters_verification_codes(self):
        assert not _is_newsletter_content("503913 is your Substack verification code")

    def test_filters_welcome_emails(self):
        assert not _is_newsletter_content("Welcome to Real Vision")

    def test_filters_payment_notices(self):
        assert not _is_newsletter_content("Your Recurring Payment Will Process in the Next 72 Hours")

    def test_filters_list_confirmations(self):
        assert not _is_newsletter_content("You're on the Hidden Market Gems list !")


class TestGetSourceForEmail:
    def test_finds_macromicro(self):
        source = get_source_for_email('"MacroMicro.me" <web@mg.macromicro.me>')
        assert source is not None
        assert source.source_id == "macromicro"

    def test_finds_stockunlocked(self):
        source = get_source_for_email("Stock Unlocked <noreply@stockunlocked.com>")
        assert source is not None
        assert source.source_id == "stockunlocked"

    def test_finds_substack_sources(self):
        source = get_source_for_email("Doomberg <doomberg@substack.com>")
        assert source is not None
        assert source.source_id == "doomberg"

    def test_returns_none_for_unknown(self):
        assert get_source_for_email("random@unknown.com") is None


class TestEmailToRawDocument:
    def test_converts_newsletter_email(self):
        doc = email_to_raw_document(
            message_id="abc123",
            subject="Energy Inflation in the US-Iran Conflict",
            from_header='"MacroMicro.me" <web@mg.macromicro.me>',
            date_header="Fri, 03 Apr 2026 02:03:06 +0000",
            body_html="<p>The Strait of Hormuz now sits at the fulcrum of global risk. Oil prices surging.</p>",
        )
        assert doc is not None
        assert doc.source_id == "macromicro"
        assert "Hormuz" in doc.raw_text
        assert doc.title == "Energy Inflation in the US-Iran Conflict"
        assert "macro" in doc.tags

    def test_skips_welcome_email(self):
        doc = email_to_raw_document(
            message_id="abc456",
            subject="Welcome to Real Vision",
            from_header="Real Vision <info@realvision.com>",
            date_header="Fri, 03 Apr 2026 23:10:08 -0400",
            body_html="<p>Welcome! You're now part of the community.</p>",
        )
        assert doc is None

    def test_skips_unknown_sender(self):
        doc = email_to_raw_document(
            message_id="xyz789",
            subject="Great analysis",
            from_header="random@unknown.com",
            date_header="Fri, 03 Apr 2026 12:00:00 +0000",
            body_html="<p>Some content here that is long enough to pass the length check for testing.</p>",
        )
        assert doc is None

    def test_skips_short_body(self):
        doc = email_to_raw_document(
            message_id="short1",
            subject="Energy Update",
            from_header='"MacroMicro.me" <web@mg.macromicro.me>',
            date_header="Fri, 03 Apr 2026 02:03:06 +0000",
            body_html="<p>Hi</p>",
        )
        assert doc is None


class TestBuildGmailQuery:
    def test_includes_all_sources(self):
        query = build_gmail_query(days=7)
        assert "from:web@mg.macromicro.me" in query
        assert "from:noreply@stockunlocked.com" in query
        assert "newer_than:7d" in query

    def test_custom_days(self):
        query = build_gmail_query(days=30)
        assert "newer_than:30d" in query

    def test_specific_sources(self):
        sources = [s for s in NEWSLETTER_SOURCES if s.source_id == "macromicro"]
        query = build_gmail_query(sources=sources, days=14)
        assert "from:web@mg.macromicro.me" in query
        assert "from:noreply@stockunlocked.com" not in query

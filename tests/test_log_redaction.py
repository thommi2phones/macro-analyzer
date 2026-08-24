"""Credentials must not reach the log files.

The launchd jobs redirect stdout/stderr to ~/Library/Logs, and several
providers carry the credential in the URL that httpx logs at INFO. A
regression here writes a live key to disk once an hour, silently, so
these are pinned rather than left to review.
"""
from __future__ import annotations

import logging

from macro_positioning.core.log_redaction import (
    SecretRedactingFilter,
    install,
    scrub,
)


def test_fred_api_key_query_param_is_scrubbed():
    url = ("GET https://api.stlouisfed.org/fred/series/observations"
           "?series_id=NFCI&api_key=de6eb13dbfef65cb098408ac31c45863&file_type=json")
    out = scrub(url, [])
    assert "de6eb13dbfef65cb098408ac31c45863" not in out
    assert "api_key=<redacted>" in out
    assert "series_id=NFCI" in out          # non-secret params survive


def test_telegram_bot_token_path_segment_is_scrubbed():
    url = ("GET https://api.telegram.org/"
           "bot8854570939:AAGD-C9MbdStdIBPOMlazgAyb_MOgvHfMR8/sendMessage")
    out = scrub(url, [])
    assert "AAGD-C9MbdStdIBPOMlazgAyb_MOgvHfMR8" not in out
    assert "/bot<redacted>/sendMessage" in out


def test_exact_secret_is_scrubbed_even_outside_a_url():
    secret = "super-secret-value-1234567890"
    assert secret not in scrub(f"connecting with {secret} now", [secret])


def test_short_settings_values_are_not_treated_as_secrets(monkeypatch):
    """A short 'secret' would match half the log — an fred_api_key of
    "test" would redact the word test everywhere. scrub() honours whatever
    the caller passes; the length guard belongs to _settings_secrets."""
    from macro_positioning.core import log_redaction
    from macro_positioning.core.settings import settings

    monkeypatch.setattr(settings, "fred_api_key", "test", raising=False)
    monkeypatch.setattr(settings, "finnhub_api_key",
                        "a-long-enough-credential-value", raising=False)
    found = log_redaction._settings_secrets()
    assert "test" not in found
    assert "a-long-enough-credential-value" in found


def test_clean_lines_are_untouched():
    line = "STEP OK  news  7.1s  90/90 persisted"
    assert scrub(line, []) == line


def test_filter_rewrites_the_record_and_never_drops_it(caplog):
    f = SecretRedactingFilter()
    record = logging.LogRecord(
        name="httpx", level=logging.INFO, pathname=__file__, lineno=1,
        msg="HTTP Request: GET https://x/y?api_key=%s ok",
        args=("abcdef0123456789",), exc_info=None,
    )
    assert f.filter(record) is True          # must not swallow the line
    assert "abcdef0123456789" not in record.getMessage()
    assert "api_key=<redacted>" in record.getMessage()


def test_install_attaches_to_existing_handlers():
    logger = logging.getLogger("test_redaction_install")
    logger.handlers = [logging.NullHandler()]
    install(logger)
    assert any(
        isinstance(flt, SecretRedactingFilter)
        for h in logger.handlers for flt in h.filters
    )

"""Gmail token health reporting.

The Gmail step fails about weekly with `invalid_grant`, because the OAuth
consent screen is in Testing status and Google expires those refresh
tokens after 7 days. token_health() is what turns that from a silent
STEP FAIL in a log nobody reads into a prompt — so its states are pinned.
"""
from __future__ import annotations

import json

import pytest

from macro_positioning.core.settings import settings
from macro_positioning.ingestion import personal_gmail


@pytest.fixture
def creds_present(tmp_path, monkeypatch):
    """Pretend the OAuth client file exists; point the token at tmp."""
    client = tmp_path / "client.json"
    client.write_text("{}")
    monkeypatch.setattr(personal_gmail, "PERSONAL_CREDENTIALS_PATH", client)
    monkeypatch.setattr(settings, "personal_gmail_token_path",
                        str(tmp_path / "token.json"), raising=False)
    return tmp_path


def test_missing_token_asks_for_reauth(creds_present):
    health = personal_gmail.token_health()
    assert health.state == "missing"
    assert health.needs_action is True
    assert personal_gmail.REAUTH_COMMAND in health.message


def test_missing_oauth_client_is_distinct_from_missing_token(tmp_path, monkeypatch):
    """These need different fixes, so they must not collapse into one state."""
    monkeypatch.setattr(personal_gmail, "PERSONAL_CREDENTIALS_PATH",
                        tmp_path / "nope.json")
    health = personal_gmail.token_health()
    assert health.state == "no_credentials"
    assert health.needs_action is True


def test_unreadable_token_does_not_raise(creds_present):
    (creds_present / "token.json").write_text("not json")
    health = personal_gmail.token_health()
    assert health.needs_action is True
    assert health.state == "missing"


def test_revoked_refresh_token_names_the_real_cause(creds_present, monkeypatch):
    """invalid_grant is the 7-day testing-status expiry. The message has to
    say so — otherwise it reads as a mysterious auth error every week."""
    (creds_present / "token.json").write_text(json.dumps({
        "token": "x", "refresh_token": "y", "client_id": "c",
        "client_secret": "s", "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": personal_gmail.SCOPES,
        "expiry": "2020-01-01T00:00:00Z",
    }))

    def boom(self, request):
        raise RuntimeError("('invalid_grant: Bad Request', {'error': 'invalid_grant'})")

    monkeypatch.setattr(
        "google.oauth2.credentials.Credentials.refresh", boom, raising=False
    )
    health = personal_gmail.token_health()
    assert health.state == "revoked"
    assert health.needs_action is True
    assert "7 days" in health.message
    assert personal_gmail.REAUTH_COMMAND in health.message


def test_health_serializes_for_logging(creds_present):
    payload = personal_gmail.token_health().as_dict()
    assert set(payload) == {"state", "message", "needs_action", "expiry", "hours_left"}
    json.dumps(payload)          # must be log-safe

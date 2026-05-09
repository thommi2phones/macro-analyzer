"""Tests for the macro-brain HTTP surface."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from macro_brain.api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["service"] == "macro-brain"


def test_regime_current_returns_a_regime(client):
    r = client.get("/regime/current?hint=commodity_expansion")
    assert r.status_code == 200
    body = r.json()
    assert body["thesis_regime"] == "commodity_expansion"
    assert body["framework_regime"] == "commodity_led_inflation"


def test_regime_refresh(client):
    r = client.post("/regime/refresh?hint=dovish_liquidity_wave")
    assert r.status_code == 200
    body = r.json()
    assert body["thesis_regime"] == "dovish_liquidity_wave"
    assert body["framework_regime"] == "risk_on_expansion"


def test_score_endpoint_minimal(client):
    payload = {
        "asset_ticker": "URNM",
        "asset_class": "equity",
        "setup_type": "commodity_breakout",
        "entry_zone": 100.0,
        "stop_loss": 95.0,
        "target": 115.0,
        "psychology_state": {
            "entry_planned_in_advance": True,
            "position_size_predefined": True,
            "setup_matches_playbook": True,
        },
    }
    r = client.post("/score", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "score_id" in body
    assert "raw_total_score" in body
    assert 0 <= body["adjusted_total_score"] <= 100
    assert body["position_size_tier"] in ("tier_1", "tier_2", "tier_3", "avoid")
    assert "feature_vector" in body["reasoning_trail"]


def test_score_uses_cached_regime_when_missing(client):
    # First call regime/current to seed cache
    client.get("/regime/current?hint=dovish_liquidity_wave")
    payload = {
        "asset_ticker": "QQQ",
        "asset_class": "equity",
        "setup_type": "breakout_continuation",
        "entry_zone": 500.0,
        "stop_loss": 490.0,
        "target": 530.0,
    }
    r = client.post("/score", json=payload)
    assert r.status_code == 200
    body = r.json()
    # The cached regime should have driven the macro alignment
    assert body["regime_id"] is not None


def test_synthesize_stub_returns_passthrough(client):
    payload = {
        "documents": [
            {"title": "Doomberg: energy security update", "source_id": "doomberg"},
            {"title": "Forward Guidance: rates path", "source_id": "forward_guidance"},
        ],
        "active_regime": "commodity_led_inflation",
    }
    r = client.post("/synthesize", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert len(body["theses"]) == 2

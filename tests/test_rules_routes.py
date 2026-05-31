"""FastAPI tests for the /api/integration/trade-check route."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from macro_positioning.db.schema import initialize_database
from macro_positioning.rules import reset_caches


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    reset_caches()
    from macro_positioning.core.settings import settings

    monkeypatch.setattr(settings, "base_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "sqlite:///rules.db")
    db_path = tmp_path / "rules.db"
    initialize_database(db_path)

    # Bring config files into tmp so the loaders find them under base_dir.
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(exist_ok=True)
    real_root = Path(__file__).resolve().parents[1]
    for name in ("risk_caps.json", "correlation_buckets.json"):
        (cfg_dir / name).write_bytes((real_root / "config" / name).read_bytes())

    reset_caches()
    from macro_positioning.api.rules_routes import router

    app = FastAPI()
    app.include_router(router)
    yield TestClient(app), db_path
    reset_caches()


def _payload(**overrides) -> dict:
    base = {
        "ticker": "NVDA",
        "side": "long",
        "entry": 500.0,
        "stop": 475.0,
        "position_size": 8.0,
        "account_equity": 100_000.0,
        "confluence_subscores": {"pattern": 3, "fib": 2, "indicator": 1},
        "setup_category": "flag",
        "tps": [525.0, 550.0],
        "mode": "advisory",
    }
    base.update(overrides)
    return base


def test_trade_check_clean_trade_returns_decision(client):
    tc, _ = client
    r = tc.post("/api/integration/trade-check", json=_payload())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["approved"] is True
    assert body["confluence"]["total"] == 6
    assert body["risk_pct"] == pytest.approx(0.002)
    assert body["violations"] == []


def test_trade_check_advisory_returns_violations_but_approves(client):
    tc, _ = client
    # insufficient confluence
    r = tc.post(
        "/api/integration/trade-check",
        json=_payload(confluence_subscores={"pattern": 1, "fib": 1, "indicator": 1}),
    )
    body = r.json()
    assert body["approved"] is True  # advisory
    codes = {v["code"] for v in body["violations"]}
    assert "confluence_insufficient" in codes


def test_trade_check_enforce_blocks_on_hard(client):
    tc, _ = client
    r = tc.post(
        "/api/integration/trade-check",
        json=_payload(
            mode="enforce",
            confluence_subscores={"pattern": 1, "fib": 1, "indicator": 1},
        ),
    )
    body = r.json()
    assert body["approved"] is False


def test_trade_check_validation_422_on_bad_confluence(client):
    tc, _ = client
    bad = _payload()
    bad["confluence_subscores"]["pattern"] = 9  # ge=0, le=3
    r = tc.post("/api/integration/trade-check", json=bad)
    assert r.status_code == 422


def test_trade_check_validation_422_on_negative_equity(client):
    tc, _ = client
    r = tc.post("/api/integration/trade-check", json=_payload(account_equity=0.0))
    assert r.status_code == 422


def test_trade_check_portfolio_aware(client):
    tc, db = client
    # Seed an open BTC trade
    with sqlite3.connect(db) as conn:
        aid = f"asset-{uuid.uuid4().hex[:8]}"
        conn.execute(
            "INSERT INTO assets (asset_id, ticker, asset_name, asset_class) VALUES (?,?,?,?)",
            (aid, "BTC", "BTC", "equity"),
        )
        conn.execute(
            """INSERT INTO trades (
                trade_id, asset_id, entry_date, entry_price, position_size,
                stop_loss, status
            ) VALUES (?,?,?,?,?,?,?)""",
            (f"trd-{uuid.uuid4().hex[:8]}", aid, "2026-05-01T00:00:00Z", 60_000.0, 0.01, 57_000.0, "open"),
        )
        conn.commit()
    r = tc.post(
        "/api/integration/trade-check",
        json=_payload(ticker="ETH", entry=3000.0, stop=2850.0, position_size=0.2),
    )
    body = r.json()
    codes = {v["code"] for v in body["violations"]}
    assert "bucket_trade_count_exceeded" in codes
    assert body["exposure"]["concurrent_trades"] == 1

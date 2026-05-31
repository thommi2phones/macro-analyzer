"""FastAPI tests for POST/GET /api/trades/{trade_id}/plan."""

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
    monkeypatch.setattr(settings, "database_url", "sqlite:///plan.db")
    db = tmp_path / "plan.db"
    initialize_database(db)

    # Bring config files into tmp/config so rules.load_buckets / load_caps find them
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(exist_ok=True)
    real_root = Path(__file__).resolve().parents[1]
    for name in ("risk_caps.json", "correlation_buckets.json"):
        (cfg_dir / name).write_bytes((real_root / "config" / name).read_bytes())
    reset_caches()

    from macro_positioning.api.trade_plan_routes import router
    app = FastAPI()
    app.include_router(router)
    yield TestClient(app), db
    reset_caches()


def _seed_trade(db_path: Path, trade_id: str = "trd-1", ticker: str = "NVDA") -> None:
    with sqlite3.connect(db_path) as conn:
        aid = f"asset-{uuid.uuid4().hex[:8]}"
        conn.execute(
            "INSERT INTO assets (asset_id, ticker, asset_name, asset_class) VALUES (?,?,?,?)",
            (aid, ticker, ticker, "equity"),
        )
        conn.execute(
            """INSERT INTO trades (
                trade_id, asset_id, entry_date, entry_price, position_size,
                stop_loss, status
            ) VALUES (?,?,?,?,?,?,?)""",
            (trade_id, aid, "2026-05-01T00:00:00Z", 100.0, 1.0, 95.0, "open"),
        )
        conn.commit()


def _payload(**overrides) -> dict:
    base = {
        "planned_entry": 500.0,
        "planned_stop": 475.0,
        "planned_size": 8.0,
        "planned_tps": [525.0, 550.0],
        "planned_account_equity": 100_000.0,
        "planned_setup_category": "flag",
        "planned_confluence_subscores": {"pattern": 3, "fib": 2, "indicator": 1},
        "planned_entry_strategy": "breakout_retest",
        "notes": "test",
    }
    base.update(overrides)
    return base


def test_create_plan_persists_and_hydrates_trade(client):
    tc, db = client
    _seed_trade(db)

    r = tc.post("/api/trades/trd-1/plan", json=_payload())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plan_id"].startswith("plan-")
    assert body["planned_confluence_score"] == 6
    # NVDA → tech_megacap bucket
    assert body["planned_correlated_bucket"] == "tech_megacap"
    # risk_pct = |500-475|*8 / 100000 = 0.002
    assert body["planned_risk_pct"] == pytest.approx(0.002)

    # Trade row was hydrated with the rule columns
    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT setup_category, confluence_score, account_risk_pct, "
            "correlated_bucket, entry_followed_retest FROM trades WHERE trade_id='trd-1'"
        ).fetchone()
    assert row == ("flag", 6, pytest.approx(0.002), "tech_megacap", 1)


def test_create_plan_409_on_duplicate(client):
    tc, db = client
    _seed_trade(db)
    r1 = tc.post("/api/trades/trd-1/plan", json=_payload())
    assert r1.status_code == 200
    r2 = tc.post("/api/trades/trd-1/plan", json=_payload(planned_entry=999.0))
    assert r2.status_code == 409


def test_create_plan_404_on_unknown_trade(client):
    tc, _ = client
    r = tc.post("/api/trades/ghost/plan", json=_payload())
    assert r.status_code == 404


def test_create_plan_422_on_bad_subscore(client):
    tc, db = client
    _seed_trade(db)
    bad = _payload()
    bad["planned_confluence_subscores"]["pattern"] = 9
    r = tc.post("/api/trades/trd-1/plan", json=bad)
    assert r.status_code == 422


def test_create_plan_422_on_nonpositive_entry(client):
    tc, db = client
    _seed_trade(db)
    r = tc.post("/api/trades/trd-1/plan", json=_payload(planned_entry=0))
    assert r.status_code == 422


def test_get_plan_returns_404_when_missing(client):
    tc, db = client
    _seed_trade(db)
    r = tc.get("/api/trades/trd-1/plan")
    assert r.status_code == 404


def test_get_plan_after_create(client):
    tc, db = client
    _seed_trade(db)
    tc.post("/api/trades/trd-1/plan", json=_payload())
    r = tc.get("/api/trades/trd-1/plan")
    assert r.status_code == 200
    body = r.json()
    assert body["planned_entry"] == 500.0
    assert body["planned_tps"] == [525.0, 550.0]


def test_strategy_drives_retest_flag(client):
    tc, db = client
    _seed_trade(db)
    tc.post(
        "/api/trades/trd-1/plan",
        json=_payload(planned_entry_strategy="breakout_impulse"),
    )
    with sqlite3.connect(db) as conn:
        flag = conn.execute(
            "SELECT entry_followed_retest FROM trades WHERE trade_id='trd-1'"
        ).fetchone()[0]
    assert flag == 0

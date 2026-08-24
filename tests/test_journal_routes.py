"""FastAPI route tests for journal_routes.

Uses a per-test temp sqlite DB, mounted on a fresh FastAPI app so we
don't pull in main.py's pipeline/repository init.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from macro_positioning.db.schema import initialize_database


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # sqlite_path is a computed property over base_dir + database_url —
    # redirect both so the routes (and feedback_writer's calibration log
    # under base_dir/data/) land in tmp.
    from macro_positioning.core.settings import settings
    # Create the schema BEFORE pointing settings at this file.
    # initialize_database refuses to create a *brand-new* DB at whatever
    # path settings currently resolves to — that guard exists because a
    # smoke test once fell back to the production path and wiped it. A
    # test legitimately building its own temp DB has to init first, then
    # redirect, which is the order the other fixtures in tests/ use.
    (tmp_path / "data").mkdir(exist_ok=True)
    db_path = tmp_path / "routes.db"
    initialize_database(db_path)
    monkeypatch.setattr(settings, "base_dir", tmp_path)
    monkeypatch.setattr(settings, "database_url", "sqlite:///routes.db")

    from macro_positioning.api.journal_routes import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app), db_path


def _seed_open_trade(conn: sqlite3.Connection, trade_id: str, ticker: str = "TST") -> None:
    asset_id = f"asset-{uuid.uuid4().hex[:8]}"
    conn.execute(
        "INSERT INTO assets (asset_id, ticker, asset_name, asset_class) VALUES (?,?,?,?)",
        (asset_id, ticker, ticker, "equity"),
    )
    conn.execute(
        """INSERT INTO trades (
            trade_id, asset_id, entry_date, entry_price, position_size,
            stop_loss, status
        ) VALUES (?,?,?,?,?,?,?)""",
        (trade_id, asset_id, "2026-05-01T00:00:00Z", 100.0, 1.0, 95.0, "open"),
    )
    conn.commit()


def _valid_payload(**overrides) -> dict:
    base = {
        "thesis_validity": "fully_right",
        "sources_credited": ["src.a", "src.b"],
        "execution_scores": {"entry": 4, "stop": 5, "sizing": 3, "exit": 4},
        "setup_score_hindsight": "right",
        "surprise_factor": ["macro"],
        "surprise_note": None,
        "lesson": "Trust the regime tag.",
        "would_retake": "yes",
        "free_form_notes": None,
    }
    base.update(overrides)
    return base


def test_webhook_flips_status_and_pending_returns_it(client):
    tc, db = client
    with sqlite3.connect(db) as conn:
        _seed_open_trade(conn, "trd-1", "AAA")

    r = tc.post(
        "/api/integration/trade-close",
        json={
            "trade_id": "trd-1",
            "exit_date": "2026-05-09T14:30:00Z",
            "exit_price": 110.0,
            "pnl_percent": 10.0,
            "pnl": 1000.0,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["review_status"] == "closed_pending_review"

    pending = tc.get("/api/reviews/pending").json()
    assert len(pending) == 1
    assert pending[0]["trade_id"] == "trd-1"
    assert pending[0]["ticker"] == "AAA"
    assert pending[0]["exit_price"] == 110.0


def test_post_review_returns_review_id_and_feedback_summary(client):
    tc, db = client
    with sqlite3.connect(db) as conn:
        _seed_open_trade(conn, "trd-1")
    tc.post("/api/integration/trade-close", json={"trade_id": "trd-1", "pnl_percent": 3.0, "pnl": 300.0})

    r = tc.post("/api/reviews/trd-1", json=_valid_payload())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["review_id"].startswith("rev-")
    assert body["review_status"] == "closed_reviewed"
    assert body["feedback_summary"]["source_outcomes_written"] == 2
    assert body["feedback_summary"]["calibration_appended"] is True

    # Pending queue now empty
    assert tc.get("/api/reviews/pending").json() == []


def test_get_review_404_when_missing(client):
    tc, _ = client
    r = tc.get("/api/reviews/nonexistent")
    assert r.status_code == 404


def test_get_review_after_submit(client):
    tc, db = client
    with sqlite3.connect(db) as conn:
        _seed_open_trade(conn, "trd-2")
    tc.post("/api/integration/trade-close", json={"trade_id": "trd-2", "pnl_percent": 1.0, "pnl": 100.0})
    tc.post("/api/reviews/trd-2", json=_valid_payload(lesson="Stopped out cleanly."))

    r = tc.get("/api/reviews/trd-2")
    assert r.status_code == 200
    assert r.json()["lesson"] == "Stopped out cleanly."


def test_post_review_invalid_payload_returns_422(client):
    tc, db = client
    with sqlite3.connect(db) as conn:
        _seed_open_trade(conn, "trd-3")
    # Bad enum
    r = tc.post("/api/reviews/trd-3", json=_valid_payload(thesis_validity="maybe"))
    assert r.status_code == 422
    # Execution score out of range
    r = tc.post("/api/reviews/trd-3", json=_valid_payload(
        execution_scores={"entry": 9, "stop": 5, "sizing": 3, "exit": 4}
    ))
    assert r.status_code == 422
    # Blank lesson
    r = tc.post("/api/reviews/trd-3", json=_valid_payload(lesson="   "))
    assert r.status_code == 422


def test_post_review_unknown_trade_returns_404(client):
    tc, _ = client
    r = tc.post("/api/reviews/missing-trade", json=_valid_payload())
    assert r.status_code == 404


def test_webhook_invalid_payload_returns_422(client):
    tc, _ = client
    r = tc.post("/api/integration/trade-close", json={})  # missing trade_id
    assert r.status_code == 422


def test_webhook_unknown_trade_returns_404(client):
    tc, _ = client
    r = tc.post("/api/integration/trade-close", json={"trade_id": "ghost"})
    assert r.status_code == 404


def test_recent_reviews_filtering_via_route(client):
    tc, db = client
    with sqlite3.connect(db) as conn:
        _seed_open_trade(conn, "trd-a", "AAA")
        _seed_open_trade(conn, "trd-b", "BBB")
    tc.post("/api/integration/trade-close", json={"trade_id": "trd-a", "pnl_percent": 2.0, "pnl": 200.0})
    tc.post("/api/integration/trade-close", json={"trade_id": "trd-b", "pnl_percent": -1.0, "pnl": -100.0})
    tc.post("/api/reviews/trd-a", json=_valid_payload(lesson="A win"))
    tc.post("/api/reviews/trd-b", json=_valid_payload(thesis_validity="fully_wrong", lesson="B loss"))

    all_recent = tc.get("/api/reviews/recent").json()
    assert {r["trade_id"] for r in all_recent} == {"trd-a", "trd-b"}

    only_a = tc.get("/api/reviews/recent", params={"ticker": "AAA"}).json()
    assert [r["trade_id"] for r in only_a] == ["trd-a"]

    only_wrong = tc.get(
        "/api/reviews/recent", params={"thesis_validity": "fully_wrong"}
    ).json()
    assert [r["trade_id"] for r in only_wrong] == ["trd-b"]

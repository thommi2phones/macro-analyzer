"""Passing on a system suggestion, and what brings it back.

The desk reviews names the system proposes as concepts. Saying no has to
stick — but not forever: the point of recording the pass is that the
system can raise the name again when the case for it has actually
changed. These tests pin the re-raise bar, which api/funnel.py computes
and the SPA only compares against.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from macro_positioning.api.funnel import (
    RERAISE_AFTER_DAYS,
    RERAISE_SCORE_STEP,
    RERAISE_STEP_CAP,
    router,
)
from macro_positioning.db.schema import initialize_database


@pytest.fixture
def client(isolate_database):
    from fastapi import FastAPI

    # allow_reinit=True is correct here, not a guard bypass: conftest's
    # isolate_database already redirected settings at this throwaway file,
    # and the guard reads "brand-new DB at settings.sqlite_path" as the
    # production-wipe signature. forbid_production_database is what keeps
    # the real DB safe.
    initialize_database(isolate_database, allow_reinit=True)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _pass(client, asset, score=61.0, side="WATCH"):
    r = client.post(
        "/api/funnel/suggestion-reviews",
        json={"asset_id": asset, "score_at_review": score, "side_at_review": side},
    )
    assert r.status_code == 200
    return r.json()["review"]


def test_passing_records_the_bar_the_name_must_clear_to_return(client):
    review = _pass(client, "COPX", score=61.0)
    assert review["verdict"] == "passed"
    assert review["reviewCount"] == 1
    assert review["reraiseAboveScore"] == 61.0 + RERAISE_SCORE_STEP
    back = datetime.fromisoformat(review["reraiseAfter"])
    reviewed = datetime.fromisoformat(review["reviewedAt"])
    assert back - reviewed == timedelta(days=RERAISE_AFTER_DAYS)


def test_passing_again_raises_the_bar(client):
    _pass(client, "COPX", score=61.0)
    second = _pass(client, "COPX", score=70.0)
    assert second["reviewCount"] == 2
    assert second["reraiseAboveScore"] == 70.0 + RERAISE_SCORE_STEP * 2


def test_the_bar_stops_climbing_at_the_cap(client):
    for _ in range(RERAISE_STEP_CAP + 3):
        review = _pass(client, "COPX", score=61.0)
    assert review["reviewCount"] == RERAISE_STEP_CAP + 3
    assert review["reraiseAboveScore"] == 61.0 + RERAISE_SCORE_STEP * RERAISE_STEP_CAP


def test_a_pass_replaces_the_previous_one_rather_than_stacking_rows(client):
    _pass(client, "COPX", score=61.0, side="WATCH")
    _pass(client, "COPX", score=70.0, side="LONG")
    rows = client.get("/api/funnel/suggestion-reviews").json()["reviews"]
    assert [r["asset"] for r in rows] == ["COPX"]
    assert rows[0]["sideAtReview"] == "LONG"
    assert rows[0]["scoreAtReview"] == 70.0


def test_a_score_less_bar_leaves_the_time_rule_as_the_only_way_back(client):
    review = _pass(client, "DBA", score=None)
    assert review["reraiseAboveScore"] is None
    assert review["reraiseAfter"] is not None


def test_un_passing_puts_the_name_straight_back(client):
    _pass(client, "COPX")
    r = client.delete("/api/funnel/suggestion-reviews/COPX")
    assert r.status_code == 200
    assert r.json()["removed"] is True
    assert client.get("/api/funnel/suggestion-reviews").json()["reviews"] == []


def test_un_passing_a_name_that_was_never_passed_is_not_an_error(client):
    r = client.delete("/api/funnel/suggestion-reviews/NEVER")
    assert r.status_code == 200
    assert r.json()["removed"] is False


def test_reviews_reach_the_desk_payload_with_their_thresholds(client, monkeypatch):
    _pass(client, "COPX", score=61.0)
    from macro_positioning.dashboard import desk_data

    rows = desk_data.build_suggestion_reviews_section()
    assert [r["asset"] for r in rows] == ["COPX"]
    assert rows[0]["reraiseAboveScore"] == 61.0 + RERAISE_SCORE_STEP


def test_the_payload_survives_a_database_without_the_table(tmp_path, monkeypatch):
    """A pre-migration DB must not blank the funnel — it just has no reviews."""
    import sqlite3

    from macro_positioning.core.settings import settings
    from macro_positioning.dashboard import desk_data

    db = tmp_path / "bare" / "bare.db"
    db.parent.mkdir(parents=True)
    sqlite3.connect(db).close()
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{db}")
    assert desk_data.build_suggestion_reviews_section() == []

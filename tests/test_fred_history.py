"""Tests for FRED historical persistence layer."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from macro_positioning.db.schema import initialize_database
from macro_positioning.market.fred_history import (
    FredObservation,
    change_over,
    incremental_refresh,
    latest_observation_date,
    latest_value,
    series_at_date,
    upsert_observations,
    value_at_or_before,
)


@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    p = tmp_path / "test.db"
    initialize_database(p)
    conn = sqlite3.connect(p)
    yield conn
    conn.close()


def _obs(series_id: str, d: str, v: float) -> FredObservation:
    return FredObservation(
        series_id=series_id,
        observation_date=date.fromisoformat(d),
        value=v,
        fetched_at=datetime.now(UTC),
    )


def test_schema_creates_fred_observations_table(tmp_path: Path):
    p = tmp_path / "schema.db"
    initialize_database(p)
    with sqlite3.connect(p) as c:
        row = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='fred_observations'"
        ).fetchone()
        assert row is not None


def test_upsert_inserts_rows(db):
    n = upsert_observations(db, [
        _obs("NFCI", "2026-01-01", -0.5),
        _obs("NFCI", "2026-01-08", -0.4),
    ])
    assert n == 2
    count = db.execute("SELECT COUNT(*) FROM fred_observations").fetchone()[0]
    assert count == 2


def test_upsert_is_idempotent(db):
    upsert_observations(db, [_obs("NFCI", "2026-01-01", -0.5)])
    upsert_observations(db, [_obs("NFCI", "2026-01-01", -0.5)])
    upsert_observations(db, [_obs("NFCI", "2026-01-01", -0.5)])
    count = db.execute("SELECT COUNT(*) FROM fred_observations").fetchone()[0]
    assert count == 1


def test_upsert_replaces_value_on_revision(db):
    upsert_observations(db, [_obs("NFCI", "2026-01-01", -0.5)])
    upsert_observations(db, [_obs("NFCI", "2026-01-01", -0.6)])
    v = latest_value(db, "NFCI")
    assert v == -0.6


def test_latest_value_picks_most_recent_date(db):
    upsert_observations(db, [
        _obs("NFCI", "2026-01-01", -0.5),
        _obs("NFCI", "2026-02-01", -0.3),
        _obs("NFCI", "2026-01-15", -0.4),
    ])
    assert latest_value(db, "NFCI") == -0.3


def test_latest_value_missing_returns_none(db):
    assert latest_value(db, "NOPE") is None


def test_latest_observation_date(db):
    upsert_observations(db, [
        _obs("NFCI", "2026-01-01", -0.5),
        _obs("NFCI", "2026-02-01", -0.3),
    ])
    assert latest_observation_date(db, "NFCI") == date(2026, 2, 1)


def test_value_at_or_before_exact_match(db):
    upsert_observations(db, [
        _obs("NFCI", "2026-01-01", -0.5),
        _obs("NFCI", "2026-02-01", -0.3),
    ])
    found = value_at_or_before(db, "NFCI", date(2026, 1, 1))
    assert found == (date(2026, 1, 1), -0.5)


def test_value_at_or_before_falls_back_to_earlier(db):
    upsert_observations(db, [
        _obs("NFCI", "2026-01-01", -0.5),
        _obs("NFCI", "2026-02-01", -0.3),
    ])
    # ask for 2026-01-15: should return Jan 01 row
    found = value_at_or_before(db, "NFCI", date(2026, 1, 15))
    assert found == (date(2026, 1, 1), -0.5)


def test_value_at_or_before_returns_none_when_all_after(db):
    upsert_observations(db, [_obs("NFCI", "2026-02-01", -0.3)])
    found = value_at_or_before(db, "NFCI", date(2026, 1, 1))
    assert found is None


def test_change_over_computes_delta(db):
    # 28 days apart
    upsert_observations(db, [
        _obs("NFCI", "2026-01-01", -0.5),
        _obs("NFCI", "2026-01-29", -0.2),
    ])
    delta = change_over(db, "NFCI", days=28, ref_date=date(2026, 1, 29))
    assert delta == pytest.approx(0.3, abs=1e-9)


def test_change_over_uses_or_before(db):
    upsert_observations(db, [
        _obs("NFCI", "2026-01-01", -0.5),
        _obs("NFCI", "2026-01-15", -0.4),  # closest at-or-before for 28d ago of 2026-02-05
        _obs("NFCI", "2026-02-05", -0.2),
    ])
    delta = change_over(db, "NFCI", days=28, ref_date=date(2026, 2, 5))
    # 28d before 2026-02-05 is 2026-01-08; nearest ≤ is 2026-01-01 (-0.5)
    assert delta == pytest.approx(-0.2 - (-0.5), abs=1e-9)


def test_change_over_returns_none_when_no_history(db):
    assert change_over(db, "NOPE", days=28) is None


def test_series_at_date_returns_value(db):
    upsert_observations(db, [_obs("NFCI", "2026-01-01", -0.5)])
    assert series_at_date(db, "NFCI", date(2026, 1, 5)) == -0.5


def test_change_over_partial_history_returns_none(db):
    upsert_observations(db, [_obs("NFCI", "2026-02-01", -0.3)])
    # ref defaults to today; prior_target is 28d before — no history that early
    delta = change_over(db, "NFCI", days=28, ref_date=date(2026, 2, 1))
    assert delta is None


# ------------------------------------------------------------------
# Provider integration via a stubbed fetch_history
# ------------------------------------------------------------------


class _StubProvider:
    """Mimics FREDMarketDataProvider.fetch_history without network."""

    def __init__(self, payload: dict[str, list[FredObservation]]):
        self._payload = payload
        self.calls: list[tuple[str, str]] = []

    def fetch_history(self, series_id, start="1900-01-01", end=None):
        self.calls.append((series_id, start))
        return list(self._payload.get(series_id, []))


def test_incremental_refresh_idempotent(db):
    rows = [_obs("NFCI", "2026-05-01", -0.4), _obs("NFCI", "2026-05-08", -0.5)]
    stub = _StubProvider({"NFCI": rows})
    counts1 = incremental_refresh(stub, db, ["NFCI"], window_days=14)
    counts2 = incremental_refresh(stub, db, ["NFCI"], window_days=14)
    assert counts1["NFCI"] == 2
    assert counts2["NFCI"] == 2  # still 2 rows attempted to upsert
    total = db.execute("SELECT COUNT(*) FROM fred_observations").fetchone()[0]
    assert total == 2  # PK collapses


def test_incremental_refresh_skips_failing_series(db):
    class _Boom:
        def fetch_history(self, sid, start="1900-01-01", end=None):
            if sid == "BAD":
                raise RuntimeError("boom")
            return [_obs("OK", "2026-05-01", 1.23)]

    counts = incremental_refresh(_Boom(), db, ["BAD", "OK"], window_days=14)
    assert counts["BAD"] == 0
    assert counts["OK"] == 1
    assert latest_value(db, "OK") == 1.23

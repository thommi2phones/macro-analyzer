"""DB-first compute_fci parity + quadrant trajectory tests."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from macro_positioning.core.models import MarketObservation
from macro_positioning.db.schema import initialize_database
from macro_positioning.market.fred_history import FredObservation, upsert_observations
from macro_positioning.market.macro_indicators import (
    classify_growth_inflation_quadrant,
    compute_fci,
)


@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    p = tmp_path / "i.db"
    initialize_database(p)
    conn = sqlite3.connect(p)
    yield conn
    conn.close()


def _live_obs(sid: str, value: float, market="financial_conditions", unit="index") -> MarketObservation:
    return MarketObservation(
        observation_id=f"id-{sid}",
        market=market,
        metric=sid,
        value=f"{value} {unit}",
        source=f"FRED:{sid}",
    )


def _row(sid: str, d: str, v: float) -> FredObservation:
    return FredObservation(
        series_id=sid,
        observation_date=date.fromisoformat(d),
        value=v,
        fetched_at=datetime.now(UTC),
    )


def test_compute_fci_db_matches_live(db):
    # NFCI dominant
    upsert_observations(db, [
        _row("NFCI", "2026-05-01", -0.42),
        _row("ANFCI", "2026-05-01", -0.30),
        _row("STLFSI4", "2026-05-01", -0.10),
        _row("VIXCLS", "2026-05-01", 18.0),
        _row("TEDRATE", "2026-05-01", 0.4),
        _row("BAMLH0A0HYM2", "2026-05-01", 3.5),
    ])
    live = [
        _live_obs("NFCI", -0.42),
        _live_obs("ANFCI", -0.30),
        _live_obs("STLFSI4", -0.10),
        _live_obs("VIXCLS", 18.0),
        _live_obs("TEDRATE", 0.4),
        _live_obs("BAMLH0A0HYM2", 3.5),
    ]
    fci_db = compute_fci(conn=db)
    fci_live = compute_fci(live)
    assert fci_db.score == pytest.approx(fci_live.score, abs=1e-6)
    assert fci_db.label == fci_live.label
    assert fci_db.primary_driver == fci_live.primary_driver
    assert set(fci_db.components.keys()) == set(fci_live.components.keys())
    for k in fci_db.components:
        assert fci_db.components[k] == pytest.approx(fci_live.components[k], abs=1e-6)


def test_compute_fci_db_empty_returns_neutral(db):
    fci = compute_fci(conn=db)
    assert fci.label == "neutral"
    assert fci.primary_driver == "unavailable"


def test_compute_fci_db_with_only_subindicators(db):
    upsert_observations(db, [
        _row("VIXCLS", "2026-05-01", 35.0),
        _row("BAMLH0A0HYM2", "2026-05-01", 6.0),
    ])
    fci = compute_fci(conn=db)
    # No NFCI so score is the average of normalised components — both positive (tightening)
    assert fci.score > 0.0
    assert "NFCI" not in fci.components


def test_compute_fci_observations_path_back_compat():
    """Old call signature still works (positional observations only)."""
    obs = [_live_obs("NFCI", -0.5)]
    fci = compute_fci(obs)
    assert fci.score == -0.5
    assert fci.label == "easing"


def test_quadrant_trajectory_improving():
    today = [
        _live_obs("A191RL1Q225SBEA", 3.0, market="growth", unit="%"),
        _live_obs("T10YIE", 1.8, market="rates", unit="%"),
    ]
    prior = [
        _live_obs("A191RL1Q225SBEA", 2.0, market="growth", unit="%"),
        _live_obs("T10YIE", 2.5, market="rates", unit="%"),
    ]
    q = classify_growth_inflation_quadrant(today, prior_observations=prior)
    assert q.growth_4w_delta == pytest.approx(1.0, abs=1e-6)
    assert q.inflation_4w_delta == pytest.approx(-0.7, abs=1e-6)
    assert q.trajectory == "improving"


def test_quadrant_trajectory_deteriorating():
    today = [
        _live_obs("A191RL1Q225SBEA", 1.0, market="growth", unit="%"),
        _live_obs("T10YIE", 3.5, market="rates", unit="%"),
    ]
    prior = [
        _live_obs("A191RL1Q225SBEA", 2.5, market="growth", unit="%"),
        _live_obs("T10YIE", 2.5, market="rates", unit="%"),
    ]
    q = classify_growth_inflation_quadrant(today, prior_observations=prior)
    assert q.trajectory == "deteriorating"


def test_quadrant_trajectory_unknown_when_prior_absent():
    today = [_live_obs("A191RL1Q225SBEA", 3.0, market="growth", unit="%")]
    q = classify_growth_inflation_quadrant(today)
    assert q.trajectory == "unknown"
    assert q.growth_4w_delta is None
    assert q.inflation_4w_delta is None


def test_quadrant_trajectory_flat_when_deltas_tiny():
    today = [
        _live_obs("A191RL1Q225SBEA", 2.001, market="growth", unit="%"),
        _live_obs("T10YIE", 2.501, market="rates", unit="%"),
    ]
    prior = [
        _live_obs("A191RL1Q225SBEA", 2.0, market="growth", unit="%"),
        _live_obs("T10YIE", 2.5, market="rates", unit="%"),
    ]
    q = classify_growth_inflation_quadrant(today, prior_observations=prior)
    assert q.trajectory == "flat"

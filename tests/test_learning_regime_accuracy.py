"""Tests for learning/regime_accuracy.py (ML loop item 5)."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from macro_positioning.db.schema import initialize_database
from macro_positioning.learning.regime_accuracy import regime_accuracy


NOW = datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC)


def _conn(tmp_path: Path) -> sqlite3.Connection:
    db = tmp_path / "ra.db"
    initialize_database(db)
    return sqlite3.connect(db)


def _insert_classification(conn, *, label: str, asof: datetime, classification_id: str | None = None):
    classification_id = classification_id or f"c-{uuid.uuid4().hex[:8]}"
    conn.execute(
        """INSERT INTO regime_classifications
           (classification_id, asof, label, confidence, rationale, call_id, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (classification_id, asof.isoformat(), label, 0.8, None, None, asof.isoformat()),
    )


def _insert_price(conn, ticker: str, observed_at: datetime, close: float):
    conn.execute(
        """INSERT OR REPLACE INTO prices
           (price_id, ticker, observed_at, timeframe, open, high, low, close, volume, provider, fetched_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            f"p-{uuid.uuid4().hex[:8]}", ticker,
            observed_at.date().isoformat(), "1D",
            close, close, close, close, 0, "test", NOW.isoformat(),
        ),
    )


def _price_path(conn, ticker: str, pub: datetime, entry: float, exit_: float, h: int = 30):
    _insert_price(conn, ticker, pub - timedelta(days=1), entry)
    _insert_price(conn, ticker, pub, entry)
    _insert_price(conn, ticker, pub + timedelta(days=h), exit_)
    _insert_price(conn, ticker, pub + timedelta(days=h + 3), exit_)


def test_regime_accuracy_empty_table_informative_meta(tmp_path: Path):
    conn = _conn(tmp_path)
    out = regime_accuracy(conn)
    assert out["_meta"]["n_classifications"] == 0
    assert out["by_month"] == []
    assert "LLM-agents chat hasn't merged" in out["_meta"]["message"]


def test_regime_accuracy_confirms_and_violates(tmp_path: Path):
    conn = _conn(tmp_path)
    asof = NOW - timedelta(days=120)
    # One risk_on_expansion call confirmed (SPY up >= 2%)
    _insert_classification(conn, label="risk_on_expansion", asof=asof)
    _price_path(conn, "SPY", asof, 400.0, 410.0)
    # One risk_on_expansion call violated (SPY down)
    asof2 = NOW - timedelta(days=90)
    _insert_classification(conn, label="risk_on_expansion", asof=asof2)
    _price_path(conn, "SPY", asof2, 400.0, 380.0)
    conn.commit()

    out = regime_accuracy(conn, now=NOW)
    assert out["_meta"]["n_in_window"] == 2
    overall = out["overall"]
    assert overall["n_confirmed"] == 1
    assert overall["n_violated"] == 1
    assert overall["confirmed_rate"] == pytest.approx(0.5)


def test_regime_accuracy_pending_when_no_price_data(tmp_path: Path):
    conn = _conn(tmp_path)
    asof = NOW - timedelta(days=5)
    _insert_classification(conn, label="risk_on_expansion", asof=asof)
    conn.commit()
    out = regime_accuracy(conn, now=NOW)
    assert out["overall"]["n_pending"] == 1
    assert out["overall"]["n_confirmed"] == 0


def test_regime_accuracy_no_config_for_label(tmp_path: Path):
    conn = _conn(tmp_path)
    asof = NOW - timedelta(days=120)
    _insert_classification(conn, label="some_unrecognized_label", asof=asof)
    conn.commit()
    out = regime_accuracy(conn, now=NOW)
    assert out["overall"]["n_no_config"] == 1


def test_regime_accuracy_buckets_by_month(tmp_path: Path):
    """Two classifications in different months. Use 3-month spacing so
    the synthetic per-classification price paths don't collide on shared
    (ticker, observed_at) keys."""
    conn = _conn(tmp_path)
    asof_jan = datetime(2026, 1, 15, tzinfo=UTC)
    asof_apr = datetime(2026, 4, 15, tzinfo=UTC)
    _insert_classification(conn, label="risk_on_expansion", asof=asof_jan)
    _insert_classification(conn, label="risk_on_expansion", asof=asof_apr)
    _price_path(conn, "SPY", asof_jan, 400.0, 410.0)
    _price_path(conn, "SPY", asof_apr, 420.0, 430.0)
    conn.commit()

    out = regime_accuracy(conn, now=NOW)
    buckets = {b["bucket"]: b for b in out["by_month"]}
    assert "2026-01" in buckets and "2026-04" in buckets
    assert buckets["2026-01"]["n_confirmed"] == 1
    assert buckets["2026-04"]["n_confirmed"] == 1

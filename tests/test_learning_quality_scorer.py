"""Tests for learning/quality_scorer.py (ML loop item 4)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from macro_positioning.db.schema import initialize_database
from macro_positioning.learning.quality_scorer import (
    backfill_quality_scores,
    quality_summary,
    _score_regime_call,
    _score_trade_outcome_call,
)


NOW = datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC)


def _conn(tmp_path: Path) -> sqlite3.Connection:
    db = tmp_path / "q.db"
    initialize_database(db)
    return sqlite3.connect(db)


def _insert_call(
    conn,
    *,
    call_id: str | None = None,
    agent_name: str = "regime_classifier",
    called_at: datetime | None = None,
    output_payload: dict | None = None,
    model_version: str | None = "gemini-2.5-pro@regime_classifier@v1",
    quality_score: float | None = None,
    attributed_trade_id: str | None = None,
    attributed_outcome_pnl: float | None = None,
    call_type: str | None = None,
):
    call_id = call_id or f"c-{uuid.uuid4().hex[:8]}"
    conn.execute(
        """INSERT INTO agent_call_log (
              call_id, agent_name, called_at, model_provider, model_name,
              prompt_version, input_payload_json, output_payload_json,
              success, model_version, quality_score,
              attributed_trade_id, attributed_outcome_pnl, call_type
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            call_id, agent_name, (called_at or NOW).isoformat(),
            "gemini", "gemini-2.5-pro", "regime_classifier@v1",
            "{}", json.dumps(output_payload or {}),
            1, model_version, quality_score,
            attributed_trade_id, attributed_outcome_pnl, call_type,
        ),
    )
    return call_id


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


def _price_path(conn, ticker: str, pub: datetime, entry: float, exit_: float, horizon: int = 30):
    _insert_price(conn, ticker, pub - timedelta(days=1), entry)
    _insert_price(conn, ticker, pub, entry)
    _insert_price(conn, ticker, pub + timedelta(days=horizon), exit_)
    _insert_price(conn, ticker, pub + timedelta(days=horizon + 3), exit_)


# ---------------------------------------------------------------------------
# Pure-function tests
# ---------------------------------------------------------------------------

def test_score_regime_call_no_payload():
    score, ev = _score_regime_call(None, NOW, {}, {})
    assert score is None
    assert ev["reason"] == "no output_payload_json"


def test_score_regime_call_no_label():
    score, ev = _score_regime_call(json.dumps({"foo": "bar"}), NOW, {}, {})
    assert score is None
    assert "no regime label" in ev["reason"]


def test_score_regime_call_no_expectations():
    payload = json.dumps({"parsed": {"regime": "unknown_regime"}})
    score, ev = _score_regime_call(payload, NOW, {}, {"some_regime": {"expectations": []}})
    assert score is None


def test_score_trade_outcome_call_branches():
    s, _ = _score_trade_outcome_call(None, None)
    assert s is None
    s, _ = _score_trade_outcome_call("t1", None)
    assert s is None
    s, _ = _score_trade_outcome_call("t1", 5.0)
    assert s == 1.0
    s, _ = _score_trade_outcome_call("t1", -3.0)
    assert s == 0.0


# ---------------------------------------------------------------------------
# Backfill integration
# ---------------------------------------------------------------------------

def test_backfill_empty_table_safe(tmp_path: Path):
    conn = _conn(tmp_path)
    out = backfill_quality_scores(conn)
    assert out["examined"] == 0
    assert out["updated"] == 0
    assert "table empty" in out["_meta"]["message"]


def test_backfill_regime_call_confirmed_gets_quality_1(tmp_path: Path):
    """SPY up >= 2% at 30d → risk_on_expansion regime call confirmed."""
    conn = _conn(tmp_path)
    pub = NOW - timedelta(days=120)
    _insert_call(
        conn, call_id="rc1", called_at=pub,
        output_payload={"parsed": {"regime": "risk_on_expansion"}},
    )
    # SPY 400 → 410 (+2.5%) at 30d → expectation met
    _price_path(conn, "SPY", pub, 400.0, 410.0)
    # Negation expectation: VIX down 5%. Provide neutral bars so the
    # negation column is "unknown" — primary expectations alone suffice.
    conn.commit()

    out = backfill_quality_scores(conn, now=NOW)
    assert out["updated"] == 1
    q = conn.execute("SELECT quality_score FROM agent_call_log WHERE call_id='rc1'").fetchone()[0]
    assert q == 1.0


def test_backfill_regime_call_violated_gets_quality_0(tmp_path: Path):
    """SPY down → risk_on_expansion regime call violated."""
    conn = _conn(tmp_path)
    pub = NOW - timedelta(days=120)
    _insert_call(
        conn, call_id="rc1", called_at=pub,
        output_payload={"parsed": {"regime": "risk_on_expansion"}},
    )
    _price_path(conn, "SPY", pub, 400.0, 380.0)  # -5%
    conn.commit()
    out = backfill_quality_scores(conn, now=NOW)
    assert out["updated"] == 1
    q = conn.execute("SELECT quality_score FROM agent_call_log WHERE call_id='rc1'").fetchone()[0]
    assert q == 0.0


def test_backfill_regime_call_no_price_data_yet_left_null(tmp_path: Path):
    """No prices in table → score stays NULL (conservative)."""
    conn = _conn(tmp_path)
    pub = NOW - timedelta(days=5)
    _insert_call(
        conn, call_id="rc1", called_at=pub,
        output_payload={"parsed": {"regime": "risk_on_expansion"}},
    )
    conn.commit()
    out = backfill_quality_scores(conn, now=NOW)
    assert out["left_null"] == 1
    q = conn.execute("SELECT quality_score FROM agent_call_log WHERE call_id='rc1'").fetchone()[0]
    assert q is None


def test_backfill_does_not_overwrite_existing_quality(tmp_path: Path):
    """LLM-agents may write quality_score directly; never overwrite."""
    conn = _conn(tmp_path)
    pub = NOW - timedelta(days=120)
    _insert_call(
        conn, call_id="rc1", called_at=pub,
        output_payload={"parsed": {"regime": "risk_on_expansion"}},
        quality_score=0.42,
    )
    _price_path(conn, "SPY", pub, 400.0, 410.0)
    conn.commit()
    out = backfill_quality_scores(conn, now=NOW)
    assert out["examined"] == 0  # WHERE quality_score IS NULL filter
    q = conn.execute("SELECT quality_score FROM agent_call_log WHERE call_id='rc1'").fetchone()[0]
    assert q == 0.42


def test_backfill_trade_outcome_agent(tmp_path: Path):
    conn = _conn(tmp_path)
    _insert_call(
        conn, call_id="t1", agent_name="orchestrator",
        attributed_trade_id="trade-1", attributed_outcome_pnl=4.2,
    )
    _insert_call(
        conn, call_id="t2", agent_name="orchestrator",
        attributed_trade_id="trade-2", attributed_outcome_pnl=-1.0,
    )
    conn.commit()
    backfill_quality_scores(conn, now=NOW)
    q1 = conn.execute("SELECT quality_score FROM agent_call_log WHERE call_id='t1'").fetchone()[0]
    q2 = conn.execute("SELECT quality_score FROM agent_call_log WHERE call_id='t2'").fetchone()[0]
    assert q1 == 1.0
    assert q2 == 0.0


def test_backfill_unknown_agent_left_null_not_crash(tmp_path: Path):
    conn = _conn(tmp_path)
    _insert_call(conn, call_id="x1", agent_name="chart_vision")
    conn.commit()
    out = backfill_quality_scores(conn, now=NOW)
    assert out["examined"] == 1
    assert out["left_null"] == 1


def test_quality_summary_stratifies_by_model_version(tmp_path: Path):
    conn = _conn(tmp_path)
    pub = NOW - timedelta(days=120)
    # Two regime calls under v1 prompt (both confirmed)
    _insert_call(conn, call_id="v1a", called_at=pub,
                 model_version="gemini-2.5-pro@regime_classifier@v1",
                 output_payload={"parsed": {"regime": "risk_on_expansion"}},
                 quality_score=1.0)
    _insert_call(conn, call_id="v1b", called_at=pub,
                 model_version="gemini-2.5-pro@regime_classifier@v1",
                 output_payload={"parsed": {"regime": "risk_on_expansion"}},
                 quality_score=0.5)
    # One call under v2 prompt (violated)
    _insert_call(conn, call_id="v2a", called_at=pub,
                 model_version="gemini-2.5-pro@regime_classifier@v2",
                 output_payload={"parsed": {"regime": "risk_on_expansion"}},
                 quality_score=0.0)
    conn.commit()
    out = quality_summary(conn)
    versions = {r["model_version"]: r for r in out["by_agent_and_version"]}
    v1 = versions["gemini-2.5-pro@regime_classifier@v1"]
    v2 = versions["gemini-2.5-pro@regime_classifier@v2"]
    assert v1["n_calls"] == 2
    assert v1["avg_quality"] == pytest.approx(0.75)
    assert v2["avg_quality"] == pytest.approx(0.0)


def test_quality_summary_empty(tmp_path: Path):
    conn = _conn(tmp_path)
    out = quality_summary(conn)
    assert out["_meta"]["n_total"] == 0
    assert out["by_agent"] == []

"""Tests for learning/retraining_triggers.py (ML loop item 6)."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from macro_positioning.db.schema import initialize_database
from macro_positioning.learning.retraining_triggers import (
    retrain_status,
    should_retrain,
    DEFAULT_THRESHOLDS,
    KNOWN_AGENTS,
)


NOW = datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC)


def _conn(tmp_path: Path) -> sqlite3.Connection:
    db = tmp_path / "rt.db"
    initialize_database(db)
    return sqlite3.connect(db)


def _insert_call(
    conn,
    *,
    call_id: str | None = None,
    agent_name: str = "regime_classifier",
    called_at: datetime | None = None,
    quality_score: float | None = None,
):
    call_id = call_id or f"c-{uuid.uuid4().hex[:8]}"
    conn.execute(
        """INSERT INTO agent_call_log (
              call_id, agent_name, called_at, model_provider, model_name,
              prompt_version, input_payload_json, output_payload_json,
              success, quality_score
           ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            call_id, agent_name, (called_at or NOW).isoformat(),
            "gemini", "gemini-2.5-pro", "p@v1",
            "{}", "{}", 1, quality_score,
        ),
    )


def test_should_retrain_empty_corpus_does_not_flag(tmp_path: Path):
    conn = _conn(tmp_path)
    out = should_retrain(conn, "regime_classifier", now=NOW)
    assert out["flag"] is False
    assert "no logged calls" in out["reason"]
    assert out["evidence"]["corpus_depth"] == 0


def test_should_retrain_quality_floor_breach_flags(tmp_path: Path):
    """20 recent rows averaging quality 0.3 → below 0.55 floor → flagged."""
    conn = _conn(tmp_path)
    for i in range(20):
        _insert_call(
            conn,
            agent_name="regime_classifier",
            called_at=NOW - timedelta(days=5 + i % 10),
            quality_score=0.3,
        )
    conn.commit()
    out = should_retrain(conn, "regime_classifier", now=NOW)
    assert out["flag"] is True
    assert "avg quality_score" in out["reason"]


def test_should_retrain_quality_drop_relative_to_prior_window(tmp_path: Path):
    """Prior window quality 0.85, recent 0.5 → drop of 0.35 → flagged."""
    conn = _conn(tmp_path)
    # Prior window: 31..59 days ago, quality 0.85
    for i in range(15):
        _insert_call(
            conn,
            agent_name="regime_classifier",
            called_at=NOW - timedelta(days=40 + i),
            quality_score=0.85,
        )
    # Recent window: 0..29 days ago, quality 0.5
    for i in range(15):
        _insert_call(
            conn,
            agent_name="regime_classifier",
            called_at=NOW - timedelta(days=i),
            quality_score=0.5,
        )
    conn.commit()
    out = should_retrain(conn, "regime_classifier", now=NOW)
    assert out["flag"] is True
    # Either floor breach or drop-trigger fires.
    assert "quality" in out["reason"]


def test_should_retrain_no_trigger_when_healthy(tmp_path: Path):
    conn = _conn(tmp_path)
    # 5 fresh calls all at quality 0.9 — below min_corpus, fresh → no flag
    for i in range(5):
        _insert_call(
            conn,
            agent_name="regime_classifier",
            called_at=NOW - timedelta(days=i),
            quality_score=0.9,
        )
    conn.commit()
    out = should_retrain(conn, "regime_classifier", now=NOW)
    assert out["flag"] is False


def test_should_retrain_corpus_plus_age_combo(tmp_path: Path):
    """Once corpus >= min AND last call > max_age, flag fires."""
    conn = _conn(tmp_path)
    # 250 rows for regime_classifier (above min 200), all 200d old
    for i in range(250):
        _insert_call(
            conn,
            agent_name="regime_classifier",
            called_at=NOW - timedelta(days=200),
            quality_score=0.8,  # healthy quality so the only trigger is corpus+age
        )
    conn.commit()
    out = should_retrain(conn, "regime_classifier", now=NOW)
    assert out["flag"] is True
    assert "corpus depth" in out["reason"]


def test_retrain_status_iterates_known_agents(tmp_path: Path):
    conn = _conn(tmp_path)
    out = retrain_status(conn, now=NOW)
    assert out["_meta"]["n_agents_checked"] == len(KNOWN_AGENTS)
    assert {r["agent_name"] for r in out["agents"]} == set(KNOWN_AGENTS)
    assert out["_meta"]["n_flagged"] == 0
    assert "empty" in out["_meta"]["message"]


def test_retrain_status_counts_flagged(tmp_path: Path):
    conn = _conn(tmp_path)
    # Make narrative_synthesizer flag via the quality-floor branch:
    # 15 recent calls all at quality 0.2
    for i in range(15):
        _insert_call(
            conn,
            agent_name="narrative_synthesizer",
            called_at=NOW - timedelta(days=i),
            quality_score=0.2,
        )
    conn.commit()
    out = retrain_status(conn, now=NOW)
    flagged = [r for r in out["agents"] if r["flag"]]
    assert any(r["agent_name"] == "narrative_synthesizer" for r in flagged)
    assert out["_meta"]["n_flagged"] >= 1

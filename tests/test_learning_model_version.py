"""Tests for learning/model_version_writer.py (ML loop item 7)."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from macro_positioning.db.schema import initialize_database
from macro_positioning.learning.model_version_writer import (
    backfill_model_versions,
    compose_model_version,
    version_stats,
)


NOW = datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC)


def _conn(tmp_path: Path) -> sqlite3.Connection:
    db = tmp_path / "v.db"
    initialize_database(db)
    return sqlite3.connect(db)


def _insert_call(
    conn,
    *,
    call_id: str | None = None,
    agent_name: str = "regime_classifier",
    model_name: str = "gemini-2.5-pro",
    prompt_version: str = "regime_classifier@v1",
    model_version: str | None = None,
    called_at: datetime | None = None,
    success: int = 1,
):
    call_id = call_id or f"c-{uuid.uuid4().hex[:8]}"
    conn.execute(
        """INSERT INTO agent_call_log (
              call_id, agent_name, called_at, model_provider, model_name,
              prompt_version, input_payload_json, output_payload_json,
              success, model_version
           ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            call_id, agent_name, (called_at or NOW).isoformat(),
            "gemini", model_name, prompt_version,
            "{}", "{}", success, model_version,
        ),
    )
    return call_id


def test_compose_model_version_canonical():
    assert compose_model_version("gemini-2.5-pro", "regime_classifier@v1") == \
        "gemini-2.5-pro@regime_classifier@v1"


def test_compose_model_version_tolerant_to_blanks():
    assert compose_model_version("", "regime_classifier@v1") == "regime_classifier@v1"
    assert compose_model_version("gemini-2.5-pro", "") == "gemini-2.5-pro"
    assert compose_model_version("", "") == "unknown"


def test_backfill_populates_null_rows_using_existing_fields(tmp_path: Path):
    conn = _conn(tmp_path)
    _insert_call(conn, call_id="c1")  # model_version NULL
    _insert_call(conn, call_id="c2", model_name="claude-sonnet-4-5",
                 prompt_version="narrative@v2")
    conn.commit()

    result = backfill_model_versions(conn)
    assert result["total_rows"] == 2
    assert result["already_versioned"] == 0
    assert result["backfilled"] == 2

    rows = dict(conn.execute(
        "SELECT call_id, model_version FROM agent_call_log").fetchall())
    assert rows["c1"] == "gemini-2.5-pro@regime_classifier@v1"
    assert rows["c2"] == "claude-sonnet-4-5@narrative@v2"


def test_backfill_never_overwrites_existing_versions(tmp_path: Path):
    """LLM-agents chat's live writes must be respected."""
    conn = _conn(tmp_path)
    _insert_call(conn, call_id="live", model_version="gemini-2.5-pro@regime_classifier@v3")
    _insert_call(conn, call_id="old")  # NULL
    conn.commit()

    result = backfill_model_versions(conn)
    assert result["already_versioned"] == 1
    assert result["backfilled"] == 1
    live = conn.execute(
        "SELECT model_version FROM agent_call_log WHERE call_id='live'").fetchone()[0]
    assert live == "gemini-2.5-pro@regime_classifier@v3"  # untouched


def test_backfill_dry_run_does_not_write(tmp_path: Path):
    conn = _conn(tmp_path)
    _insert_call(conn, call_id="c1")
    conn.commit()
    result = backfill_model_versions(conn, dry_run=True)
    assert result["backfilled"] == 1
    assert result["dry_run"] is True
    # The row in DB is still NULL
    mv = conn.execute("SELECT model_version FROM agent_call_log WHERE call_id='c1'").fetchone()[0]
    assert mv is None


def test_version_stats_empty(tmp_path: Path):
    conn = _conn(tmp_path)
    out = version_stats(conn)
    assert out["_meta"]["n_total"] == 0
    assert out["versions"] == []
    assert "no agent_call_log rows" in out["_meta"]["message"]


def test_version_stats_groups_by_agent_and_version(tmp_path: Path):
    conn = _conn(tmp_path)
    _insert_call(conn, model_version="gemini-2.5-pro@regime_classifier@v1", success=1)
    _insert_call(conn, model_version="gemini-2.5-pro@regime_classifier@v1", success=1)
    _insert_call(conn, model_version="gemini-2.5-pro@regime_classifier@v2", success=0)
    conn.commit()
    out = version_stats(conn)
    assert out["_meta"]["n_total"] == 3
    assert out["_meta"]["n_unversioned"] == 0
    versions = {(r["model_version"], r["agent_name"]): r for r in out["versions"]}
    v1 = versions[("gemini-2.5-pro@regime_classifier@v1", "regime_classifier")]
    assert v1["n_calls"] == 2
    assert v1["n_success"] == 2
    assert v1["success_rate"] == pytest.approx(1.0)
    v2 = versions[("gemini-2.5-pro@regime_classifier@v2", "regime_classifier")]
    assert v2["success_rate"] == pytest.approx(0.0)

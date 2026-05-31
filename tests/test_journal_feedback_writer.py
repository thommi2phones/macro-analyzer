"""Tests for journal/feedback_writer.py — fan-out into source_outcomes + calibration log."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from macro_positioning.db.schema import initialize_database
from macro_positioning.journal import feedback_writer as jfw


def _conn(tmp_path: Path) -> sqlite3.Connection:
    db = tmp_path / "fb.db"
    initialize_database(db)
    return sqlite3.connect(db)


def _seed_trade(conn: sqlite3.Connection, trade_id: str = "trd-1",
                pnl: float | None = 1050.0, pnl_percent: float | None = 3.5,
                score_at_entry: int | None = 80) -> str:
    asset_id = f"asset-{uuid.uuid4().hex[:8]}"
    conn.execute(
        "INSERT INTO assets (asset_id, ticker, asset_name, asset_class) VALUES (?,?,?,?)",
        (asset_id, "TST", "Test", "equity"),
    )
    score_id = None
    if score_at_entry is not None:
        setup_id = f"setup-{uuid.uuid4().hex[:8]}"
        conn.execute(
            """INSERT INTO technical_setups (
                setup_id, asset_id, observed_at, timeframe, setup_type,
                market_structure, technical_score
            ) VALUES (?,?,?,?,?,?,?)""",
            (setup_id, asset_id, "2026-05-01T00:00:00Z", "1D", "breakout", "uptrend", 70),
        )
        score_id = f"score-{uuid.uuid4().hex[:8]}"
        conn.execute(
            """INSERT INTO trade_scores (
                score_id, setup_id, scored_at, regime_id,
                macro_alignment_score, liquidity_score, sector_theme_score,
                technical_structure_score, volume_flow_score, risk_reward_score,
                relative_strength_score, psychology_score,
                raw_total_score, adjusted_total_score, grade, position_size_tier
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                score_id, setup_id, "2026-05-01T00:00:00Z", None,
                70, 70, 70, 70, 70, 70, 70, 70,
                560, score_at_entry, "A", "tier1",
            ),
        )
    conn.execute(
        """INSERT INTO trades (
            trade_id, asset_id, entry_date, entry_price, position_size,
            stop_loss, status, pnl, pnl_percent, score_id, review_status
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            trade_id, asset_id, "2026-05-01T00:00:00Z", 100.0, 1.0,
            95.0, "closed", pnl, pnl_percent, score_id,
            "closed_pending_review",
        ),
    )
    return trade_id


def test_apply_review_writes_one_source_outcome_per_credit(tmp_path: Path):
    conn = _conn(tmp_path)
    _seed_trade(conn, "trd-1")
    review = {
        "sources_credited": ["src.a", "src.b", "src.c"],
        "setup_score_hindsight": "right",
    }
    summary = jfw.apply_review_feedback(
        conn, "trd-1", review,
        calibration_path=tmp_path / "calib.jsonl",
    )
    conn.commit()
    assert summary["source_outcomes_written"] == 3

    rows = conn.execute(
        "SELECT source_id, attribution_weight, outcome_pnl, outcome_pnl_percent, contribution_type "
        "FROM source_outcomes WHERE trade_id = ?",
        ("trd-1",),
    ).fetchall()
    assert len(rows) == 3
    for source_id, weight, pnl, pnl_pct, ctype in rows:
        assert weight == 1 / 3
        assert pnl == 1050.0
        assert pnl_pct == 3.5
        assert ctype == "review_credited"


def test_attribution_weight_is_one_over_n(tmp_path: Path):
    conn = _conn(tmp_path)
    _seed_trade(conn, "trd-1")
    jfw.apply_review_feedback(
        conn, "trd-1",
        {"sources_credited": ["only.one"], "setup_score_hindsight": "right"},
        calibration_path=tmp_path / "calib.jsonl",
    )
    conn.commit()
    weight = conn.execute(
        "SELECT attribution_weight FROM source_outcomes WHERE trade_id = 'trd-1'"
    ).fetchone()[0]
    assert weight == 1.0


def test_no_credits_writes_zero_rows(tmp_path: Path):
    conn = _conn(tmp_path)
    _seed_trade(conn, "trd-1")
    summary = jfw.apply_review_feedback(
        conn, "trd-1",
        {"sources_credited": [], "setup_score_hindsight": "over"},
        calibration_path=tmp_path / "calib.jsonl",
    )
    conn.commit()
    assert summary["source_outcomes_written"] == 0
    n = conn.execute(
        "SELECT COUNT(*) FROM source_outcomes WHERE trade_id = 'trd-1'"
    ).fetchone()[0]
    assert n == 0


def test_calibration_log_appended(tmp_path: Path):
    conn = _conn(tmp_path)
    _seed_trade(conn, "trd-1", score_at_entry=82)
    path = tmp_path / "score_calibration.jsonl"
    summary = jfw.apply_review_feedback(
        conn, "trd-1",
        {"sources_credited": [], "setup_score_hindsight": "over"},
        now=datetime(2026, 5, 9, 12, 0, tzinfo=timezone.utc),
        calibration_path=path,
    )
    conn.commit()
    assert summary["calibration_appended"] is True
    assert path.exists()
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["trade_id"] == "trd-1"
    assert entry["score_at_entry"] == 82
    assert entry["hindsight"] == "over"


def test_calibration_skipped_for_invalid_hindsight(tmp_path: Path):
    conn = _conn(tmp_path)
    _seed_trade(conn, "trd-1")
    path = tmp_path / "calib.jsonl"
    summary = jfw.apply_review_feedback(
        conn, "trd-1",
        {"sources_credited": [], "setup_score_hindsight": None},
        calibration_path=path,
    )
    conn.commit()
    assert summary["calibration_appended"] is False
    assert not path.exists()

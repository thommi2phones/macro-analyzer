"""Tests for journal/repository.py — status state machine + CRUD."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from macro_positioning.db.schema import initialize_database
from macro_positioning.journal import repository as jrepo


def _conn(tmp_path: Path) -> sqlite3.Connection:
    db = tmp_path / "journal.db"
    initialize_database(db)
    return sqlite3.connect(db)


def _seed_trade(
    conn: sqlite3.Connection,
    trade_id: str = "trd-1",
    *,
    ticker: str = "TST",
    pnl_percent: float | None = 3.5,
    pnl: float | None = 1050.0,
    status: str = "open",
    review_status: str | None = None,
    score_at_entry: int | None = None,
    regime: str | None = None,
) -> str:
    asset_id = f"asset-{uuid.uuid4().hex[:8]}"
    score_id: str | None = None
    regime_id: str | None = None
    conn.execute(
        "INSERT INTO assets (asset_id, ticker, asset_name, asset_class) VALUES (?,?,?,?)",
        (asset_id, ticker, ticker, "equity"),
    )
    if regime is not None:
        regime_id = f"reg-{uuid.uuid4().hex[:8]}"
        conn.execute(
            """INSERT INTO macro_regimes (
                regime_id, classified_at, framework_regime, thesis_regime,
                confidence_score
            ) VALUES (?,?,?,?,?)""",
            (regime_id, "2026-05-01T00:00:00Z", regime, regime, 80),
        )
    if score_at_entry is not None:
        # trade_scores requires a setup_id FK
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
                score_id, setup_id, "2026-05-01T00:00:00Z", regime_id,
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
            95.0, status, pnl, pnl_percent, score_id, review_status,
        ),
    )
    return trade_id


def test_mark_pending_idempotent(tmp_path: Path):
    conn = _conn(tmp_path)
    _seed_trade(conn, "trd-1", status="open")
    assert jrepo.mark_pending(conn, "trd-1", exit_price=110.0) is True
    row = conn.execute(
        "SELECT status, review_status, exit_price FROM trades WHERE trade_id = 'trd-1'"
    ).fetchone()
    assert row == ("closed", "closed_pending_review", 110.0)

    # Second call: status already pending, does not reset to NULL etc
    assert jrepo.mark_pending(conn, "trd-1", exit_price=120.0) is True
    row = conn.execute(
        "SELECT status, review_status, exit_price FROM trades WHERE trade_id = 'trd-1'"
    ).fetchone()
    assert row == ("closed", "closed_pending_review", 120.0)


def test_mark_pending_unknown_returns_false(tmp_path: Path):
    conn = _conn(tmp_path)
    assert jrepo.mark_pending(conn, "missing") is False


def test_mark_pending_does_not_revert_reviewed(tmp_path: Path):
    conn = _conn(tmp_path)
    _seed_trade(conn, "trd-1", status="closed", review_status="closed_reviewed")
    assert jrepo.mark_pending(conn, "trd-1", exit_price=110.0) is True
    rs = conn.execute(
        "SELECT review_status FROM trades WHERE trade_id = 'trd-1'"
    ).fetchone()[0]
    assert rs == "closed_reviewed"


def test_list_pending_excludes_reviewed_and_open(tmp_path: Path):
    conn = _conn(tmp_path)
    _seed_trade(conn, "trd-pend", status="closed", review_status="closed_pending_review",
                ticker="AAA", score_at_entry=82, regime="risk_on")
    _seed_trade(conn, "trd-done", status="closed", review_status="closed_reviewed", ticker="BBB")
    _seed_trade(conn, "trd-open", status="open", review_status=None, ticker="CCC")
    rows = jrepo.list_pending(conn)
    assert len(rows) == 1
    r = rows[0]
    assert r["trade_id"] == "trd-pend"
    assert r["ticker"] == "AAA"
    assert r["score_at_entry"] == 82
    assert r["regime_at_entry"] == "risk_on"


def test_insert_review_flips_status_and_persists_payload(tmp_path: Path):
    conn = _conn(tmp_path)
    _seed_trade(conn, "trd-1", status="closed", review_status="closed_pending_review")
    payload = {
        "thesis_validity": "fully_right",
        "sources_credited": ["src.a", "src.b"],
        "execution_scores": {"entry": 4, "stop": 5, "sizing": 3, "exit": 4},
        "setup_score_hindsight": "right",
        "surprise_factor": ["macro"],
        "surprise_note": "Powell pivot mid-trade",
        "lesson": "Trust the regime tag.",
        "would_retake": "yes",
        "free_form_notes": None,
    }
    review_id = jrepo.insert_review(conn, "trd-1", payload)
    conn.commit()
    assert review_id.startswith("rev-")

    rs = conn.execute(
        "SELECT review_status FROM trades WHERE trade_id = 'trd-1'"
    ).fetchone()[0]
    assert rs == "closed_reviewed"

    fetched = jrepo.get_review(conn, "trd-1")
    assert fetched is not None
    assert fetched["thesis_validity"] == "fully_right"
    assert fetched["sources_credited"] == ["src.a", "src.b"]
    assert fetched["execution_scores"] == {"entry": 4, "stop": 5, "sizing": 3, "exit": 4}
    assert fetched["surprise_factor"] == ["macro"]
    assert fetched["lesson"] == "Trust the regime tag."


def test_insert_review_unknown_trade_raises(tmp_path: Path):
    conn = _conn(tmp_path)
    with pytest.raises(ValueError):
        jrepo.insert_review(conn, "missing", {"thesis_validity": "fully_right"})


def test_recent_reviews_filtering(tmp_path: Path):
    conn = _conn(tmp_path)
    _seed_trade(conn, "trd-1", ticker="AAA", status="closed",
                review_status="closed_pending_review")
    _seed_trade(conn, "trd-2", ticker="BBB", status="closed",
                review_status="closed_pending_review")
    base = datetime(2026, 5, 9, tzinfo=timezone.utc)
    jrepo.insert_review(conn, "trd-1", {
        "thesis_validity": "fully_right",
        "sources_credited": ["s1"],
        "execution_scores": {"entry": 4, "stop": 4, "sizing": 4, "exit": 4},
        "setup_score_hindsight": "right",
        "surprise_factor": [],
        "surprise_note": None,
        "lesson": "AAA worked.",
        "would_retake": "yes",
        "free_form_notes": None,
    }, completed_at=base)
    jrepo.insert_review(conn, "trd-2", {
        "thesis_validity": "fully_wrong",
        "sources_credited": ["s2"],
        "execution_scores": {"entry": 2, "stop": 2, "sizing": 2, "exit": 2},
        "setup_score_hindsight": "over",
        "surprise_factor": ["liquidity"],
        "surprise_note": None,
        "lesson": "BBB blew up.",
        "would_retake": "no",
        "free_form_notes": None,
    }, completed_at=base + timedelta(hours=1))
    conn.commit()

    all_rows = jrepo.recent_reviews(conn)
    assert [r["ticker"] for r in all_rows] == ["BBB", "AAA"]

    only_aaa = jrepo.recent_reviews(conn, ticker="aaa")
    assert len(only_aaa) == 1 and only_aaa[0]["trade_id"] == "trd-1"

    only_wrong = jrepo.recent_reviews(conn, thesis_validity="fully_wrong")
    assert len(only_wrong) == 1 and only_wrong[0]["trade_id"] == "trd-2"

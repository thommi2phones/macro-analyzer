"""Tests for learning/mention_precision.py."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from macro_positioning.db.schema import initialize_database
from macro_positioning.learning.mention_precision import mention_precision


NOW = datetime(2026, 5, 9, 12, 0, 0, tzinfo=UTC)


def _conn(tmp_path: Path) -> sqlite3.Connection:
    db = tmp_path / "mp.db"
    initialize_database(db)
    return sqlite3.connect(db)


def _insert(
    conn,
    *,
    ticker: str,
    scored_at: datetime,
    adj_total: int,
    origins: list[str] | None,
):
    asset_id = f"asset-{ticker}"
    setup_id = f"setup-{uuid.uuid4().hex[:8]}"
    score_id = f"score-{uuid.uuid4().hex[:8]}"
    conn.execute(
        "INSERT OR IGNORE INTO assets (asset_id, ticker, asset_name, asset_class) VALUES (?,?,?,?)",
        (asset_id, ticker, ticker, "equity"),
    )
    conn.execute(
        """INSERT INTO technical_setups (setup_id, asset_id, observed_at, timeframe,
              setup_type, market_structure, technical_score) VALUES (?,?,?,?,?,?,?)""",
        (setup_id, asset_id, scored_at.isoformat(), "1D", "x", "neutral", 5),
    )
    trail = json.dumps({"watchlist_origins": origins or []})
    conn.execute(
        """INSERT INTO trade_scores (
              score_id, setup_id, scored_at, regime_id,
              macro_alignment_score, liquidity_score, sector_theme_score,
              technical_structure_score, volume_flow_score, risk_reward_score,
              relative_strength_score, psychology_score,
              raw_total_score, adjusted_total_score, grade, position_size_tier,
              feature_vector_json, reasoning_trail_json
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            score_id, setup_id, scored_at.isoformat(), None,
            5, 5, 5, 5, 5, 5, 5, 5,
            adj_total, adj_total, "B", "1R",
            None, trail,
        ),
    )
    return score_id, setup_id, asset_id


def test_empty_returns_empty_shape(tmp_path: Path):
    conn = _conn(tmp_path)
    out = mention_precision(conn)
    assert out["n_promoted"] == 0
    assert out["precision_at_k"] == 0.0
    assert out["ranked_by_promotion"] == []
    # v2: informative _meta block on empty
    assert "_meta" in out
    assert "no trade_scores rows" in out["_meta"]["message"]


def test_promotion_then_score_improves_counts_as_good(tmp_path: Path):
    conn = _conn(tmp_path)
    promo_at = NOW - timedelta(days=20)
    _insert(conn, ticker="URA", scored_at=promo_at, adj_total=55, origins=["mentions:30d:w12.5"])
    # 5 days later, URA scored 75 (above default 70 threshold)
    _insert(conn, ticker="URA", scored_at=promo_at + timedelta(days=5), adj_total=75, origins=["anchor"])
    conn.commit()

    out = mention_precision(conn)
    assert out["n_promoted"] == 1
    assert out["n_good"] == 1
    assert out["precision_at_k"] == pytest.approx(1.0)
    row = out["ranked_by_promotion"][0]
    assert row["ticker"] == "URA"
    assert row["scored_well_within_horizon"] is True
    assert row["traded"] is False


def test_promotion_with_trade_counts_as_good(tmp_path: Path):
    conn = _conn(tmp_path)
    promo_at = NOW - timedelta(days=20)
    _, _, asset_id = _insert(
        conn, ticker="URA", scored_at=promo_at, adj_total=55, origins=["mentions:7d:w8.0"]
    )
    # Trade opened after promotion → "good" via (b)
    conn.execute(
        """INSERT INTO trades (trade_id, asset_id, entry_date, entry_price,
              position_size, stop_loss, status)
           VALUES (?,?,?,?,?,?,?)""",
        ("trade-1", asset_id, (promo_at + timedelta(days=2)).isoformat(),
         100.0, 1.0, 95.0, "open"),
    )
    conn.commit()

    out = mention_precision(conn)
    assert out["n_promoted"] == 1
    assert out["n_good"] == 1
    assert out["ranked_by_promotion"][0]["traded"] is True


def test_promotion_with_no_followthrough_is_not_good(tmp_path: Path):
    conn = _conn(tmp_path)
    promo_at = NOW - timedelta(days=20)
    _insert(conn, ticker="URA", scored_at=promo_at, adj_total=55, origins=["mentions:30d:w5.0"])
    # Later score is still mediocre
    _insert(conn, ticker="URA", scored_at=promo_at + timedelta(days=3), adj_total=60, origins=["anchor"])
    conn.commit()

    out = mention_precision(conn, score_threshold=70)
    assert out["n_promoted"] == 1
    assert out["n_good"] == 0
    assert out["precision_at_k"] == pytest.approx(0.0)


def test_first_promotion_per_ticker_only(tmp_path: Path):
    conn = _conn(tmp_path)
    base = NOW - timedelta(days=30)
    # Three mentions:* rows for URA — only first should count as the promotion event
    _insert(conn, ticker="URA", scored_at=base, adj_total=50, origins=["mentions:7d:w3.0"])
    _insert(conn, ticker="URA", scored_at=base + timedelta(days=1), adj_total=52, origins=["mentions:7d:w4.0"])
    _insert(conn, ticker="URA", scored_at=base + timedelta(days=10), adj_total=80, origins=["anchor"])
    conn.commit()

    out = mention_precision(conn)
    assert out["n_promoted"] == 1  # only one ticker promoted
    assert out["n_good"] == 1

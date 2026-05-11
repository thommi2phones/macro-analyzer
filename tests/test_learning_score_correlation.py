"""Tests for learning/score_outcome_correlation.py."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from macro_positioning.db.schema import initialize_database
from macro_positioning.learning.score_outcome_correlation import (
    score_outcome_correlation,
    _fisher_ci,
    _ranks,
    _spearman,
)


NOW = datetime(2026, 5, 9, 12, 0, 0, tzinfo=UTC)


def _conn(tmp_path: Path) -> sqlite3.Connection:
    db = tmp_path / "corr.db"
    initialize_database(db)
    return sqlite3.connect(db)


def _insert_score_and_trade(conn, *, adj_total: int, sub: int, pnl_pct: float):
    asset_id = f"asset-{uuid.uuid4().hex[:8]}"
    setup_id = f"setup-{uuid.uuid4().hex[:8]}"
    score_id = f"score-{uuid.uuid4().hex[:8]}"
    trade_id = f"trade-{uuid.uuid4().hex[:8]}"

    conn.execute(
        "INSERT OR IGNORE INTO assets (asset_id, ticker, asset_name, asset_class) VALUES (?,?,?,?)",
        (asset_id, "TST", "Test", "equity"),
    )
    conn.execute(
        """INSERT INTO technical_setups (setup_id, asset_id, observed_at, timeframe,
              setup_type, market_structure, technical_score)
           VALUES (?,?,?,?,?,?,?)""",
        (setup_id, asset_id, NOW.isoformat(), "1D", "x", "neutral", sub),
    )
    conn.execute(
        """INSERT INTO trade_scores (
              score_id, setup_id, scored_at, regime_id,
              macro_alignment_score, liquidity_score, sector_theme_score,
              technical_structure_score, volume_flow_score, risk_reward_score,
              relative_strength_score, psychology_score,
              raw_total_score, adjusted_total_score, grade, position_size_tier
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            score_id, setup_id, NOW.isoformat(), None,
            sub, sub, sub, sub, sub, sub, sub, sub,
            adj_total, adj_total, "B", "1R",
        ),
    )
    conn.execute(
        """INSERT INTO trades (trade_id, setup_id, score_id, asset_id,
              entry_date, entry_price, position_size, stop_loss, status, pnl_percent)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (trade_id, setup_id, score_id, asset_id, NOW.isoformat(),
         100.0, 1.0, 95.0, "closed", pnl_pct),
    )


def test_empty_returns_empty_shape(tmp_path: Path):
    conn = _conn(tmp_path)
    out = score_outcome_correlation(conn)
    assert out["n_pairs"] == 0
    # CI bounds present + None on empty data
    assert out["adjusted_total"]["spearman"] is None
    assert out["adjusted_total"]["n"] == 0
    assert out["adjusted_total"]["ci_lo"] is None
    assert out["adjusted_total"]["ci_hi"] is None
    # Informative meta on empty
    assert "_meta" in out
    assert "no closed trades" in out["_meta"]["message"]
    # A few sub-scores included
    assert out["macro_alignment"]["n"] == 0


def test_perfect_positive_correlation(tmp_path: Path):
    conn = _conn(tmp_path)
    # Score and pnl rank-monotonic → ρ = 1.0
    for adj, pnl in [(50, -5.0), (60, 1.0), (70, 3.0), (80, 8.0), (90, 15.0)]:
        _insert_score_and_trade(conn, adj_total=adj, sub=adj // 10, pnl_pct=pnl)
    conn.commit()
    out = score_outcome_correlation(conn)
    assert out["n_pairs"] == 5
    assert out["adjusted_total"]["spearman"] == pytest.approx(1.0)
    # Sub-scores were monotonic with adj as well
    assert out["macro_alignment"]["spearman"] == pytest.approx(1.0)


def test_ranks_handles_ties():
    # Two ties at value 5 → ranks should be 1, 2.5, 2.5, 4
    assert _ranks([1, 5, 5, 9]) == [1.0, 2.5, 2.5, 4.0]


def test_spearman_below_n10_has_none_pvalue():
    out = _spearman([1, 2, 3, 4, 5], [1, 2, 3, 4, 5])
    assert out["spearman"] == pytest.approx(1.0)
    assert out["n"] == 5
    assert out["p_value"] is None  # n<10 → no normal-approx p-value
    # Floating-point: ρ may be 0.9999...; Fisher CI is computed but
    # collapses near 1.0 either way. Don't assert None here — assert
    # the bounds are clipped to [-1, 1].
    if out["ci_lo"] is not None:
        assert -1.0 <= out["ci_lo"] <= out["ci_hi"] <= 1.0


def test_fisher_ci_brackets_rho():
    # Synthetic monotonic but not perfect: known ρ ≈ 0.829 for n=12
    # → CI should be wider than zero and contain the point estimate.
    xs = list(range(12))
    ys = [0, 1, 2, 3, 4, 5, 7, 6, 8, 9, 11, 10]
    out = _spearman(xs, ys)
    assert out["n"] == 12
    assert out["spearman"] is not None
    assert out["ci_lo"] is not None and out["ci_hi"] is not None
    assert out["ci_lo"] < out["spearman"] < out["ci_hi"]
    # 95% CI should be moderately tight at this n
    assert (out["ci_hi"] - out["ci_lo"]) < 1.5


def test_fisher_ci_small_n_returns_none():
    lo, hi = _fisher_ci(0.5, n=3)
    assert lo is None and hi is None
    lo, hi = _fisher_ci(0.5, n=10)
    assert lo is not None and hi is not None


def test_hindsight_overlay_sql_table_reader_folds_into_calibration(tmp_path: Path):
    """When score_hindsight_overlay has rows, score_outcome_correlation
    surfaces a calibration block summarizing bucket counts + avg gap."""
    conn = _conn(tmp_path)
    # Pre-req: at least one trade_id + review_id stub so FKs validate.
    asset_id = "asset-h"
    setup_id = "setup-h"
    score_id = "score-h"
    trade_id = "trade-h"
    review_id = "review-h"
    conn.execute(
        "INSERT INTO assets (asset_id, ticker, asset_name, asset_class) VALUES (?,?,?,?)",
        (asset_id, "HND", "Hind", "equity"),
    )
    conn.execute(
        """INSERT INTO technical_setups (setup_id, asset_id, observed_at, timeframe,
              setup_type, market_structure, technical_score) VALUES (?,?,?,?,?,?,?)""",
        (setup_id, asset_id, NOW.isoformat(), "1D", "x", "neutral", 5),
    )
    conn.execute(
        """INSERT INTO trade_scores (
              score_id, setup_id, scored_at, regime_id,
              macro_alignment_score, liquidity_score, sector_theme_score,
              technical_structure_score, volume_flow_score, risk_reward_score,
              relative_strength_score, psychology_score,
              raw_total_score, adjusted_total_score, grade, position_size_tier
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (score_id, setup_id, NOW.isoformat(), None, 7, 7, 7, 7, 7, 7, 7, 7,
         80, 80, "B", "1R"),
    )
    conn.execute(
        """INSERT INTO trades (trade_id, setup_id, score_id, asset_id, entry_date,
              entry_price, position_size, stop_loss, status, pnl_percent)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (trade_id, setup_id, score_id, asset_id, NOW.isoformat(),
         100.0, 1.0, 95.0, "closed", 4.0),
    )
    conn.execute(
        """INSERT INTO trade_reviews (
              review_id, trade_id, completed_at, thesis_validity,
              sources_credited_json, execution_scores_json,
              setup_score_hindsight, surprise_factor_json, surprise_note,
              lesson, would_retake, free_form_notes
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (review_id, trade_id, NOW.isoformat(), "fully_right", "[]", "{}",
         "over", "[]", None, None, "yes", None),
    )
    # Two hindsight rows: one 'over', one 'right'
    conn.execute(
        """INSERT INTO score_hindsight_overlay
              (overlay_id, review_id, trade_id, score_id, hindsight_verdict, recorded_at)
           VALUES (?,?,?,?,?,?)""",
        ("o-1", review_id, trade_id, score_id, "over", NOW.isoformat()),
    )
    conn.execute(
        """INSERT INTO score_hindsight_overlay
              (overlay_id, review_id, trade_id, score_id, hindsight_verdict, recorded_at)
           VALUES (?,?,?,?,?,?)""",
        ("o-2", review_id, trade_id, score_id, "right", NOW.isoformat()),
    )
    conn.commit()

    out = score_outcome_correlation(conn)
    assert "calibration" in out
    assert out["calibration"]["n"] == 2
    assert out["calibration"]["buckets"]["over"] == 1
    assert out["calibration"]["buckets"]["right"] == 1
    # Center gap: 'over' = -10, 'right' = 0 → avg -5
    assert out["calibration"]["avg_score_gap"] == pytest.approx(-5.0)


def test_open_trades_excluded(tmp_path: Path):
    conn = _conn(tmp_path)
    # Insert one closed + one open. Open shouldn't count.
    _insert_score_and_trade(conn, adj_total=80, sub=8, pnl_pct=10.0)
    # Manually insert an open trade w/ score
    asset_id = "asset-open"
    setup_id = "setup-open"
    score_id = "score-open"
    trade_id = "trade-open"
    conn.execute("INSERT OR IGNORE INTO assets VALUES (?,?,?,?,?,?,?,?)" if False else
                 "INSERT OR IGNORE INTO assets (asset_id, ticker, asset_name, asset_class) VALUES (?,?,?,?)",
                 (asset_id, "OPN", "Open", "equity"))
    conn.execute(
        """INSERT INTO technical_setups (setup_id, asset_id, observed_at, timeframe,
              setup_type, market_structure, technical_score) VALUES (?,?,?,?,?,?,?)""",
        (setup_id, asset_id, NOW.isoformat(), "1D", "x", "neutral", 5),
    )
    conn.execute(
        """INSERT INTO trade_scores (
              score_id, setup_id, scored_at, regime_id,
              macro_alignment_score, liquidity_score, sector_theme_score,
              technical_structure_score, volume_flow_score, risk_reward_score,
              relative_strength_score, psychology_score,
              raw_total_score, adjusted_total_score, grade, position_size_tier
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (score_id, setup_id, NOW.isoformat(), None, 5, 5, 5, 5, 5, 5, 5, 5, 50, 50, "C", "0.5R"),
    )
    conn.execute(
        """INSERT INTO trades (trade_id, setup_id, score_id, asset_id,
              entry_date, entry_price, position_size, stop_loss, status, pnl_percent)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (trade_id, setup_id, score_id, asset_id, NOW.isoformat(),
         100.0, 1.0, 95.0, "open", None),
    )
    conn.commit()
    out = score_outcome_correlation(conn)
    assert out["n_pairs"] == 1

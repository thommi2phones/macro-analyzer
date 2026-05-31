"""Tests for rules/gate.py — the composed evaluator."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest

from macro_positioning.db.schema import initialize_database
from macro_positioning.rules import reset_caches
from macro_positioning.rules.gate import (
    TradeProposal,
    evaluate_trade_proposal,
)


@pytest.fixture(autouse=True)
def _clear_caps_cache():
    reset_caches()
    yield
    reset_caches()


def _conn(tmp_path: Path) -> sqlite3.Connection:
    db = tmp_path / "gate.db"
    initialize_database(db)
    return sqlite3.connect(db)


def _proposal(**overrides) -> TradeProposal:
    base = dict(
        ticker="NVDA",
        side="long",
        entry=500.0,
        stop=475.0,
        position_size=8.0,
        account_equity=100_000.0,
        confluence_subscores=(3, 2, 1),  # total 6 = standard tier
        setup_category="flag",
        tps=(525.0, 550.0),
    )
    base.update(overrides)
    return TradeProposal(**base)


def test_clean_standard_trade_no_hard_violations(tmp_path: Path):
    conn = _conn(tmp_path)
    decision = evaluate_trade_proposal(_proposal(), conn)
    # 25 distance * 8 size = 200 / 100000 = 0.2% — under 1% cap.
    # Allocation 500*8 / 100000 = 4% — between 3% floor and 5% ceiling.
    assert decision.risk_pct == pytest.approx(0.002)
    assert decision.allocation_pct == pytest.approx(0.04)
    assert decision.confluence.tier == "standard"
    hard = [v for v in decision.violations if v.severity == "hard"]
    assert hard == []
    assert decision.approved is True


def test_advisory_mode_always_approves_even_on_hard_violations(tmp_path: Path):
    conn = _conn(tmp_path)
    # insufficient confluence (3 total) — would be hard in enforce
    p = _proposal(confluence_subscores=(1, 1, 1))
    decision = evaluate_trade_proposal(p, conn, mode="advisory")
    assert decision.confluence.tier == "insufficient"
    assert any(v.code == "confluence_insufficient" and v.severity == "hard" for v in decision.violations)
    assert decision.approved is True  # advisory


def test_enforce_mode_blocks_on_hard_violation(tmp_path: Path):
    conn = _conn(tmp_path)
    p = _proposal(confluence_subscores=(1, 1, 1))
    decision = evaluate_trade_proposal(p, conn, mode="enforce")
    assert decision.approved is False


def test_account_risk_exceeded_suggests_size(tmp_path: Path):
    conn = _conn(tmp_path)
    # 25pt stop distance, 201 units, equity 100k → risk = 5025/100000 = 5.025% — over 1% cap.
    p = _proposal(position_size=201.0)
    decision = evaluate_trade_proposal(p, conn, mode="enforce")
    codes = {v.code for v in decision.violations}
    assert "account_risk_exceeded" in codes
    # suggested_size for the standard 1% cap: 100000*0.01/25 = 40
    assert decision.suggested_size == pytest.approx(40.0)
    # Allocation 201 * 500 / 100000 = 100.5% — well above absolute ceiling
    assert "allocation_above_high_conviction_ceiling" in codes
    assert decision.approved is False


def test_stop_on_wrong_side(tmp_path: Path):
    conn = _conn(tmp_path)
    # Long trade with stop above entry
    p = _proposal(stop=525.0)
    decision = evaluate_trade_proposal(p, conn, mode="enforce")
    assert any(v.code == "stop_on_wrong_side" for v in decision.violations)
    assert decision.approved is False


def test_missing_tps_is_soft(tmp_path: Path):
    conn = _conn(tmp_path)
    p = _proposal(tps=())
    decision = evaluate_trade_proposal(p, conn, mode="enforce")
    codes = {(v.code, v.severity) for v in decision.violations}
    assert ("missing_tps", "soft") in codes
    # Soft alone does NOT block in enforce mode (only hard does)
    assert decision.approved is True


def test_portfolio_caps_consulted(tmp_path: Path):
    conn = _conn(tmp_path)
    # Seed an open BTC trade in the same bucket as the proposed ETH trade
    aid = f"asset-{uuid.uuid4().hex[:8]}"
    conn.execute(
        "INSERT INTO assets (asset_id, ticker, asset_name, asset_class) VALUES (?,?,?,?)",
        (aid, "BTC", "BTC", "equity"),
    )
    conn.execute(
        """INSERT INTO trades (
            trade_id, asset_id, entry_date, entry_price, position_size,
            stop_loss, status
        ) VALUES (?,?,?,?,?,?,?)""",
        (f"trd-{uuid.uuid4().hex[:8]}", aid, "2026-05-01T00:00:00Z", 60_000.0, 0.05, 57_000.0, "open"),
    )
    conn.commit()

    p = _proposal(ticker="ETH", entry=3000.0, stop=2850.0, position_size=0.3)
    decision = evaluate_trade_proposal(p, conn, mode="enforce")
    codes = {v.code for v in decision.violations}
    # max_trades_per_bucket=1, so adding ETH to crypto_l1 (already has BTC) trips
    assert "bucket_trade_count_exceeded" in codes


def test_high_conviction_tier_uses_higher_risk_cap(tmp_path: Path):
    conn = _conn(tmp_path)
    # Confluence 8 = high_conviction. Risk 1.4% — over standard 1% but under HC 1.5%
    # entry 100, stop 95.5 (4.5pt), size 311.111... → risk ≈ 1.4%
    p = _proposal(
        entry=100.0,
        stop=95.5,
        position_size=311.0,  # 4.5 * 311 = 1399.5 / 100000 = 0.013995
        confluence_subscores=(3, 3, 2),
        tps=(110.0, 120.0),
    )
    decision = evaluate_trade_proposal(p, conn, mode="enforce")
    assert decision.confluence.tier == "high_conviction"
    codes = {v.code for v in decision.violations}
    # 1.4% does NOT exceed 1.5% HC cap → no account_risk_exceeded
    assert "account_risk_exceeded" not in codes


def test_decision_serializes_cleanly(tmp_path: Path):
    conn = _conn(tmp_path)
    decision = evaluate_trade_proposal(_proposal(), conn)
    d = decision.as_dict()
    # Spot-check shape
    for k in ("approved", "mode", "confluence", "risk_pct", "allocation_pct", "exposure", "violations"):
        assert k in d
    assert isinstance(d["violations"], list)
    assert d["confluence"]["total"] == 6

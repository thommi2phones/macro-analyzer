"""Tests for rules/adherence.py — composite 0..100 scoring."""

from __future__ import annotations

import pytest

from macro_positioning.rules import reset_caches
from macro_positioning.rules.adherence import compute_adherence


@pytest.fixture(autouse=True)
def _clear_caps_cache():
    reset_caches()
    yield
    reset_caches()


def _trade(**overrides) -> dict:
    base = {
        "trade_id": "trd-1",
        "entry_price": 100.0,
        "exit_price": 110.0,
        "stop_loss": 95.0,
        "position_size": 1.0,
        "pnl_percent": 10.0,
        "confluence_score": 6,
        "account_risk_pct": 0.005,
        "entry_followed_retest": 1,
        "rule_adherence_score": None,
    }
    base.update(overrides)
    return base


def _plan(**overrides) -> dict:
    base = {
        "plan_id": "plan-1",
        "trade_id": "trd-1",
        "planned_entry": 100.0,
        "planned_stop": 95.0,
        "planned_tps": [110.0, 120.0],
        "planned_size": 1.0,
        "planned_account_equity": 100_000.0,
        "planned_risk_pct": 0.00005,
        "planned_setup_category": "flag",
        "planned_confluence_score": 6,
    }
    base.update(overrides)
    return base


def test_clean_disciplined_winner_scores_high():
    """Plan was followed exactly, hit TP, risk under cap, retest honored."""
    score = compute_adherence(_trade(), _plan(), review=None)
    assert score.score >= 90
    assert score.raw_weight == 100  # all 6 components evaluated


def test_no_plan_or_trade_returns_zero():
    score = compute_adherence({}, None, None)
    assert score.score == 0
    assert score.raw_weight == 0


def test_partial_data_redistributes():
    """Trade has confluence_score + risk_pct but no plan → only those
    components fire; score is computed over the evaluated weight."""
    score = compute_adherence(_trade(), plan=None, review=None)
    assert 0 <= score.score <= 100
    # Only risk_within_cap + followed_retest fire (plan-dependent ones skipped)
    evaluated = [c for c in score.components if c.weight > 0]
    names = {c.name for c in evaluated}
    assert "risk_within_cap" in names
    assert "followed_retest" in names
    assert "entry_fidelity" not in names


def test_entry_deviation_costs_points():
    """5% slippage on entry → zero credit for entry_fidelity."""
    trade = _trade(entry_price=105.0)  # 5% over plan
    plan = _plan()
    score = compute_adherence(trade, plan, None)
    entry = next(c for c in score.components if c.name == "entry_fidelity")
    assert entry.earned == 0.0


def test_risk_within_cap_full_credit():
    """0.5% risk on standard tier (cap 1%) → full credit."""
    trade = _trade(account_risk_pct=0.005, confluence_score=6)
    score = compute_adherence(trade, _plan(), None)
    risk = next(c for c in score.components if c.name == "risk_within_cap")
    assert risk.earned == risk.weight


def test_risk_exceeded_linear_penalty():
    """1.5% risk on standard tier (cap 1%) → halfway through linear band."""
    trade = _trade(account_risk_pct=0.015, confluence_score=6)
    score = compute_adherence(trade, _plan(), None)
    risk = next(c for c in score.components if c.name == "risk_within_cap")
    # Linear band: full at cap, zero at 2*cap → 0.015 is halfway → 50% credit
    assert risk.earned == pytest.approx(risk.weight * 0.5)


def test_followed_retest_flag():
    """Retest flag = 0 → zero credit; flag = 1 → full credit."""
    s0 = compute_adherence(_trade(entry_followed_retest=0), _plan(), None)
    s1 = compute_adherence(_trade(entry_followed_retest=1), _plan(), None)
    c0 = next(c for c in s0.components if c.name == "followed_retest")
    c1 = next(c for c in s1.components if c.name == "followed_retest")
    assert c0.earned == 0.0
    assert c1.earned == c1.weight


def test_insufficient_confluence_dings_sizing_to_zero():
    """A trade taken at insufficient confluence loses all sizing credit."""
    trade = _trade(confluence_score=2)
    plan = _plan(planned_confluence_score=2)
    score = compute_adherence(trade, plan, None)
    sizing = next(c for c in score.components if c.name == "sizing_for_confluence")
    assert sizing.earned == 0.0


def test_loser_with_honored_stop_gets_tp_credit():
    """Loser that stopped out at the planned stop is rule-abiding → full TP credit."""
    trade = _trade(pnl_percent=-5.0, exit_price=95.0)
    score = compute_adherence(trade, _plan(), None)
    tp = next(c for c in score.components if c.name == "tp_discipline")
    assert tp.earned == tp.weight


def test_serialization_shape():
    score = compute_adherence(_trade(), _plan(), None)
    d = score.as_dict()
    for k in ("score", "raw_earned", "raw_weight", "components"):
        assert k in d
    assert len(d["components"]) == 6
    for c in d["components"]:
        for k in ("name", "weight", "earned", "note"):
            assert k in c

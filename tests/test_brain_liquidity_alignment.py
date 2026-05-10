"""Tests for liquidity_alignment heuristic scorer."""

from __future__ import annotations

import pytest

from macro_brain.agents.liquidity_alignment.scorer import score_liquidity_alignment
from macro_brain.types import SetupContext


def _ctx(**feats):
    return SetupContext(asset_ticker="TEST", liquidity_features=feats)


def test_easing_aligns_with_bullish_regime_high_score():
    sub = score_liquidity_alignment(
        _ctx(
            nfci_latest=-0.4,
            nfci_4w_change=-0.3,
            regime_bullish=True,
            source="fred:NFCI",
        )
    )
    assert sub.component == "liquidity_alignment"
    assert sub.value > 0.7


def test_tightening_against_bullish_regime_low_score():
    sub = score_liquidity_alignment(
        _ctx(
            nfci_latest=0.4,
            nfci_4w_change=0.3,
            regime_bullish=True,
            source="fred:NFCI",
        )
    )
    assert sub.value < 0.3


def test_tightening_aligns_with_bearish_regime_high_score():
    sub = score_liquidity_alignment(
        _ctx(
            nfci_latest=0.4,
            nfci_4w_change=0.3,
            regime_bullish=False,
            source="fred:NFCI",
        )
    )
    assert sub.value > 0.7


def test_missing_fci_returns_neutral():
    sub = score_liquidity_alignment(_ctx(source="missing"))
    assert sub.value == 0.5
    assert "No FCI" in sub.notes


def test_only_change_present_still_scores():
    """Edge case: nfci_latest absent but 4w change is known."""
    sub = score_liquidity_alignment(
        _ctx(nfci_4w_change=-0.5, regime_bullish=True, source="fred:NFCI")
    )
    assert sub.value > 0.5


def test_db_backed_payload_yields_nonneutral_score(tmp_path):
    """Seeding NFCI history in SQLite produces a payload with real
    nfci_4w_change; the scorer should move off 0.5."""
    import sqlite3
    from datetime import UTC, date, datetime, timedelta

    from macro_positioning.db.schema import initialize_database
    from macro_positioning.market.fred_history import (
        FredObservation,
        change_over,
        latest_value,
        upsert_observations,
    )

    p = tmp_path / "nfci.db"
    initialize_database(p)
    today = date.today()
    rows = []
    # 5 weekly readings, easing trend (NFCI falling)
    for weeks_ago, val in [(4, -0.10), (3, -0.20), (2, -0.30), (1, -0.40), (0, -0.50)]:
        rows.append(FredObservation(
            series_id="NFCI",
            observation_date=today - timedelta(weeks=weeks_ago),
            value=val,
            fetched_at=datetime.now(UTC),
        ))
    with sqlite3.connect(p) as conn:
        upsert_observations(conn, rows)
        nfci_latest = latest_value(conn, "NFCI")
        nfci_4w_change = change_over(conn, "NFCI", days=28)

    assert nfci_latest == -0.50
    assert nfci_4w_change == pytest.approx(-0.40, abs=1e-9)

    sub = score_liquidity_alignment(
        _ctx(
            nfci_latest=nfci_latest,
            nfci_4w_change=nfci_4w_change,
            regime_bullish=True,
            source="fred:NFCI",
        )
    )
    assert sub.value > 0.7  # easing + bullish → strong alignment

"""Tests for actionable-signal + asset-breakdown builders in command_data.py."""
from __future__ import annotations

import pytest

from macro_positioning.core.models import Thesis, ThesisStatus, ViewDirection
from macro_positioning.dashboard import command_data as cd


def _t(thesis_id, theme, direction, confidence=0.8, assets=None, horizon="2-12 weeks"):
    """None → default to [theme]; [] → explicitly empty (preserve for tests)."""
    resolved_assets = [theme] if assets is None else list(assets)
    return Thesis(
        thesis_id=thesis_id,
        thesis=f"Test thesis {thesis_id} on {theme}",
        theme=theme,
        horizon=horizon,
        direction=ViewDirection(direction),
        assets=resolved_assets,
        confidence=confidence,
        status=ThesisStatus.active,
        source_ids=["src_test"],
    )


def test_asset_breakdown_aggregates_by_asset():
    theses = [
        _t("1", "commodities", "bullish", 0.8, assets=["gold", "oil"]),
        _t("2", "commodities", "bullish", 0.6, assets=["gold"]),
        _t("3", "energy", "bearish", 0.7, assets=["oil"]),
    ]
    breakdown = cd.build_asset_breakdown(theses)
    by_asset = {b.asset: b for b in breakdown}

    assert "gold" in by_asset
    assert "oil" in by_asset
    # gold: 0.8 + 0.6 = 1.4, all bullish
    assert by_asset["gold"].dominant_direction == "bullish"
    assert by_asset["gold"].thesis_count == 2
    # oil: 0.8 bullish vs 0.7 bearish → bullish wins
    assert by_asset["oil"].dominant_direction == "bullish"
    assert by_asset["oil"].thesis_count == 2


def test_actionable_signals_groups_by_side():
    theses = [
        _t("1", "commodities", "bullish", 0.8, assets=["gold"]),
        _t("2", "rates", "bearish", 0.7, assets=["tlt"]),
        _t("3", "crypto", "watchful", 0.5, assets=["btc"]),
    ]
    signals = cd.build_actionable_signals(theses, tactical_events=[])

    sides = {s.asset: s.side for s in signals}
    assert sides["gold"] == "LONG"
    assert sides["tlt"] == "SHORT"
    assert sides["btc"] == "WATCH"


def test_actionable_signals_order_long_then_short_then_watch():
    theses = [
        _t("watch", "fx", "watchful", 0.9, assets=["dxy"]),
        _t("short", "rates", "bearish", 0.8, assets=["tlt"]),
        _t("long", "equities", "bullish", 0.7, assets=["spy"]),
    ]
    signals = cd.build_actionable_signals(theses, tactical_events=[])
    sides_in_order = [s.side for s in signals]
    # LONG should be first, then SHORT, then WATCH
    long_idx = sides_in_order.index("LONG")
    short_idx = sides_in_order.index("SHORT")
    watch_idx = sides_in_order.index("WATCH")
    assert long_idx < short_idx < watch_idx


def test_actionable_signals_tactical_annotation_matches_symbol():
    theses = [_t("1", "commodities", "bullish", 0.85, assets=["GLD"])]
    events = [
        {"payload": {"symbol": "GLD", "setup_id": "s1", "setup_stage": "trigger"}},
        {"payload": {"symbol": "GLD", "setup_id": "s2", "setup_stage": "in_trade"}},
        {"payload": {"symbol": "SPY", "setup_id": "s3", "setup_stage": "watch"}},  # different symbol
    ]
    signals = cd.build_actionable_signals(theses, tactical_events=events)
    gld = next(s for s in signals if s.asset.lower() == "gld")
    assert gld.tactical is not None
    assert gld.tactical.active_setups == 2
    assert gld.tactical.at_entry == 1
    assert gld.tactical.in_trade == 1


def test_actionable_signals_tactical_none_when_no_match():
    theses = [_t("1", "commodities", "bullish", 0.8, assets=["gold"])]
    events = [
        {"payload": {"symbol": "SPY", "setup_id": "s1", "setup_stage": "watch"}},
    ]
    signals = cd.build_actionable_signals(theses, tactical_events=events)
    assert signals[0].tactical is None


def test_actionable_signals_theses_without_assets_are_skipped():
    theses = [
        _t("1", "macro", "bullish", 0.8, assets=[]),  # no assets — skipped
        _t("2", "commodities", "bullish", 0.7, assets=["gold"]),
    ]
    signals = cd.build_actionable_signals(theses, tactical_events=[])
    assert len(signals) == 1
    assert signals[0].asset == "gold"

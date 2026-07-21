"""Tests for the signal_alignment scorer + its wiring into the composer."""

from __future__ import annotations

from macro_brain.agents.signal_alignment.scorer import score_signal_alignment
from macro_brain.orchestrator.composer import compose
from macro_brain.types import COMPONENT_WEIGHTS, SetupContext


def _setup(agg: dict | None = None, **kw) -> SetupContext:
    return SetupContext(
        asset_ticker="NVDA",
        signal_aggregate=agg or {},
        # give it a defined invalidation so score isn't fully penalized
        entry_zone=100.0,
        stop_loss=95.0,
        target=115.0,
        **kw,
    )


# --- weights ---------------------------------------------------------------

def test_signal_alignment_is_a_weighted_component():
    assert COMPONENT_WEIGHTS["signal_alignment"] == 15
    assert sum(COMPONENT_WEIGHTS.values()) == 100


# --- scorer mapping --------------------------------------------------------

def test_no_signals_is_neutral():
    ss = score_signal_alignment(_setup({}))
    assert ss.value == 0.5
    assert "No tracked signals" in ss.notes


def test_zero_n_signals_is_neutral_even_with_stale_fields():
    ss = score_signal_alignment(_setup({"n_signals": 0, "net_bias": 9.0}))
    assert ss.value == 0.5


def test_strong_long_bias_scores_high():
    ss = score_signal_alignment(_setup({
        "n_signals": 3,
        "net_bias": 12.0,        # == _SCALE → full tilt
        "bias_direction": "long",
        "bias_confidence": 0.9,
        "alignment_score": 10,
        "long_weight": 12.0,
        "short_weight": 0.0,
    }))
    assert ss.value == 1.0
    assert "long" in ss.notes


def test_strong_short_bias_scores_low():
    ss = score_signal_alignment(_setup({
        "n_signals": 3,
        "net_bias": -12.0,
        "bias_direction": "short",
        "bias_confidence": 0.9,
        "short_weight": 12.0,
    }))
    assert ss.value == 0.0


def test_split_crowd_collapses_to_neutral():
    # equal long and short weight → net_bias 0 → no conviction
    ss = score_signal_alignment(_setup({
        "n_signals": 4,
        "net_bias": 0.0,
        "bias_direction": "neutral",
        "long_weight": 6.0,
        "short_weight": 6.0,
    }))
    assert ss.value == 0.5


def test_moderate_long_bias_scales_partway():
    # half of _SCALE → halfway between neutral and full
    ss = score_signal_alignment(_setup({
        "n_signals": 2,
        "net_bias": 6.0,
        "bias_direction": "long",
    }))
    assert ss.value == 0.75


def test_avoid_voices_push_below_neutral():
    ss = score_signal_alignment(_setup({
        "n_signals": 2,
        "net_bias": 0.0,
        "bias_direction": "watch_only",
        "avoid_count": 2,
    }))
    assert ss.value < 0.5


def test_contributing_features_preserved_for_corpus():
    ss = score_signal_alignment(_setup({
        "n_signals": 1,
        "net_bias": 4.0,
        "bias_direction": "long",
        "bias_confidence": 1.0,
        "alignment_score": 3,
    }))
    assert ss.contributing_features["net_bias"] == 4.0
    assert ss.contributing_features["n_signals"] == 1.0
    assert ss.contributing_features["alignment_score_raw"] == 3.0


# --- composer wiring: conviction now MOVES the total -----------------------

def test_conviction_lifts_the_composite_score():
    """The whole point: a strong long-conviction aggregate must raise
    adjusted_total_score vs. the same setup with no tracked signals."""
    long_agg = {
        "n_signals": 3, "net_bias": 12.0, "bias_direction": "long",
        "bias_confidence": 0.9, "alignment_score": 10,
        "long_weight": 12.0, "short_weight": 0.0,
    }
    with_conviction = compose(_setup(long_agg))
    without = compose(_setup({}))

    # signal_alignment contributes its own weighted column
    assert with_conviction.signal_alignment_score == 15   # 1.0 * 15
    assert without.signal_alignment_score == 8            # 0.5 * 15 → round(7.5)=8

    # and it flows through to the composite
    assert with_conviction.raw_total_score > without.raw_total_score

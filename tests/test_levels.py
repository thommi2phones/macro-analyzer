"""Technical agent — level synthesis (scoring/levels.py)."""

from macro_positioning.scoring.levels import (
    side_from_signal_bias,
    synthesize_levels,
)


def _base_feats(**over) -> dict:
    feats = {
        "n_bars": 200,
        "close": 100.0,
        "atr14": 2.0,
        "ma20": 96.0,
        "ma50": 92.0,
        "ema20": 97.0,
        "ema50": 94.0,
        "above_ma50": True,
        "above_ema50": True,
        "higher_lows": False,
        "lower_highs": False,
        "recent_breakout": False,
        "recent_breakdown": False,
        "prior_high_20": None,
        "prior_low_20": None,
        "swing_high_10": None,
        "swing_low_10": None,
    }
    feats.update(over)
    return feats


# ── gating ──────────────────────────────────────────────────────────

def test_no_price_no_levels():
    ls, gap = synthesize_levels({"n_bars": 0})
    assert ls is None and gap == "no_price"


def test_no_atr_no_levels():
    ls, gap = synthesize_levels({"close": 50.0, "atr14": None})
    assert ls is None and gap == "no_atr"


# ── LONG ────────────────────────────────────────────────────────────

def test_long_mechanical_fallback():
    ls, gap = synthesize_levels(_base_feats(ma20=90.0, ema20=90.0, ma50=85.0))
    assert gap is None
    assert ls.side == "LONG" and not ls.structural
    assert ls.method == "mechanical_v0"
    assert ls.entry == 100.0
    assert ls.stop == 100.0 - 2 * 2.0          # 2×ATR
    assert ls.target == 100.0 + 3 * (100.0 - ls.stop)  # 3R
    assert abs(ls.rr - 3.0) < 1e-9


def test_long_breakout_stop_below_broken_level():
    ls, _ = synthesize_levels(
        _base_feats(recent_breakout=True, prior_high_20=98.5)
    )
    assert ls.structural and ls.method == "breakout_20d"
    assert ls.stop == 98.5 - 0.5 * 2.0         # broken level − 0.5 ATR
    assert ls.target > ls.entry
    assert ls.rr == 3.0


def test_long_breakout_structure_too_far_falls_back():
    # prior high 90 → risk 100−89 = 11 = 5.5 ATR > 3.5 ATR band
    ls, _ = synthesize_levels(
        _base_feats(recent_breakout=True, prior_high_20=90.0,
                    ma20=90.0, ema20=90.0, ma50=85.0)
    )
    assert ls.method == "mechanical_v0" and not ls.structural


def test_long_pullback_to_support():
    # close 100 sits within 1 ATR of ema20=99; uptrend intact.
    ls, _ = synthesize_levels(
        _base_feats(ema20=99.0, ma20=98.5, higher_lows=True,
                    swing_low_10=97.5, prior_high_20=110.0)
    )
    assert ls.structural and ls.method == "pullback_support"
    # invalidation = min(nearest supports, swing low) − 0.5 ATR
    assert ls.stop == 97.5 - 1.0
    # prior 20-bar high above the 2.5R floor → becomes the target
    assert ls.target == 110.0
    assert ls.rr > 2.0


def test_long_pullback_target_floor_when_no_overhead_room():
    # prior high barely above entry → floor target (2.5R) wins
    ls, _ = synthesize_levels(
        _base_feats(ema20=99.0, ma20=98.5, higher_lows=True,
                    swing_low_10=97.5, prior_high_20=101.0)
    )
    risk = ls.entry - ls.stop
    assert ls.target == ls.entry + 2.5 * risk


# ── SHORT ───────────────────────────────────────────────────────────

def test_short_mechanical():
    ls, _ = synthesize_levels(
        _base_feats(ma20=110.0, ema20=110.0, ma50=115.0,
                    above_ma50=False, above_ema50=False),
        side="SHORT",
    )
    assert ls.side == "SHORT"
    assert ls.stop > ls.entry > ls.target
    assert abs(ls.rr - 3.0) < 1e-9


def test_short_breakdown():
    ls, _ = synthesize_levels(
        _base_feats(recent_breakdown=True, prior_low_20=101.5,
                    above_ma50=False, above_ema50=False),
        side="SHORT",
    )
    assert ls.structural and ls.method == "breakdown_20d"
    assert ls.stop == 101.5 + 1.0              # broken level + 0.5 ATR
    assert ls.target < ls.entry


def test_short_rally_into_resistance():
    ls, _ = synthesize_levels(
        _base_feats(above_ma50=False, above_ema50=False, lower_highs=True,
                    ema20=101.0, ma20=101.5, ma50=108.0,
                    swing_high_10=102.0, prior_low_20=88.0),
        side="SHORT",
    )
    assert ls.structural and ls.method == "rally_resistance"
    assert ls.stop == 102.0 + 1.0              # max(resistance, swing high) + 0.5 ATR
    assert ls.target == 88.0                   # prior low below the 2.5R floor


# ── serialization / side derivation ─────────────────────────────────

def test_to_dict_has_ui_fields():
    ls, _ = synthesize_levels(_base_feats(ma20=90.0, ema20=90.0, ma50=85.0))
    d = ls.to_dict()
    for key in ("side", "entry", "stop", "target", "rr", "risk_pct",
                "method", "setup", "structural", "version"):
        assert key in d
    assert d["risk_pct"] > 0


def test_side_from_signal_bias():
    assert side_from_signal_bias(None) == "LONG"
    assert side_from_signal_bias({}) == "LONG"
    assert side_from_signal_bias(
        {"bias_direction": "long", "bias_confidence": 0.9}) == "LONG"
    assert side_from_signal_bias(
        {"bias_direction": "short", "bias_confidence": 0.4}) == "LONG"
    assert side_from_signal_bias(
        {"bias_direction": "short", "bias_confidence": 0.8}) == "SHORT"
    assert side_from_signal_bias(
        {"bias_direction": "exit_bias", "bias_confidence": 1.0}) == "LONG"

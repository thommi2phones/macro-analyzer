"""Price-action structure extraction (prices/structure.py)."""

from macro_positioning.prices.provider import PriceBar
from macro_positioning.prices.structure import (
    build_structure,
    cluster_pivots,
    nearest_support,
    next_resistance,
    swing_pivots,
)


def _bars(seq, *, volume=1000):
    """Build bars from (low, high, close) triples or plain closes."""
    out = []
    for i, item in enumerate(seq):
        if isinstance(item, (int, float)):
            lo = hi = close = float(item)
        else:
            lo, hi, close = (float(x) for x in item)
        out.append(PriceBar(
            ticker="TEST", observed_at=f"2026-01-{(i % 28) + 1:02d}",
            open=close, high=hi, low=lo, close=close, volume=volume,
        ))
    return out


# --- pivots -------------------------------------------------------------

def test_swing_pivots_finds_the_obvious_peak_and_trough():
    highs = [10, 11, 12, 20, 12, 11, 10]
    lows = [9, 8, 7, 6, 7, 8, 9]
    pivots = swing_pivots(highs, lows, left=3, right=3)
    assert {"i": 3, "price": 20, "kind": "high"} in pivots
    assert {"i": 3, "price": 6, "kind": "low"} in pivots


def test_pivots_need_room_on_both_sides():
    """The last bar can't be a pivot — nothing has happened after it yet,
    so calling it one would be lookahead by another name."""
    highs = [1, 2, 3, 4, 5, 6, 99]
    lows = [1, 2, 3, 4, 5, 6, 7]
    assert not [p for p in swing_pivots(highs, lows) if p["i"] == 6]


# --- clustering ---------------------------------------------------------

def test_nearby_pivots_become_one_zone():
    pivots = [
        {"i": 5, "price": 82.10, "kind": "low"},
        {"i": 40, "price": 82.44, "kind": "low"},
        {"i": 80, "price": 81.95, "kind": "low"},
    ]
    clusters = cluster_pivots(pivots, tolerance=1.0)
    assert len(clusters) == 1
    assert len(clusters[0]["prices"]) == 3


def test_distant_pivots_stay_separate():
    pivots = [
        {"i": 5, "price": 82.0, "kind": "low"},
        {"i": 40, "price": 95.0, "kind": "low"},
    ]
    assert len(cluster_pivots(pivots, tolerance=1.0)) == 2


# --- structure map ------------------------------------------------------

def _triple_bottom_bars():
    """Repeated tests of ~80 support and ~100 resistance, close at 90.

    Each leg is jittered: real levels are zones, and a fixture where every
    touch lands on the identical tick would hide that.
    """
    seq = []
    for k, drift in enumerate((0.0, 0.4, -0.3, 0.2, -0.45, 0.35, -0.2, 0.15, -0.1)):
        seq += [
            (80 + drift, 92 - drift, 88),
            (84, 95 + drift, 93),
            (88, 100 + drift, 96),
            (85, 99 - drift, 90),
            (81 + drift, 93, 84),
            (80 - drift, 88, 82 + (k % 2) * 0.1),
        ]
    return _bars(seq + [(88, 92, 90)])


def test_repeated_lows_form_a_support_zone_below_price():
    st = build_structure(_triple_bottom_bars(), atr=4.0)
    assert st.supports, "expected support below the close"
    top = st.supports[0]
    assert top.kind == "support"
    assert top.price < 90
    assert top.touches >= 2
    assert 0.0 < top.strength <= 1.0


def test_repeated_highs_form_a_resistance_zone_above_price():
    st = build_structure(_triple_bottom_bars(), atr=4.0)
    assert st.resistances
    assert st.resistances[0].price > 90


def test_more_touches_score_stronger_than_a_single_tap():
    """A level defended repeatedly should outrank one brushed once."""
    repeated = build_structure(_triple_bottom_bars(), atr=4.0)
    many = max(repeated.levels, key=lambda lv: lv.touches)
    singles = [lv for lv in repeated.levels if lv.touches == 1]
    if singles:
        assert many.strength > min(lv.strength for lv in singles)


def test_every_level_explains_itself():
    """The card quotes `basis`, so an empty one is a silent number."""
    st = build_structure(_triple_bottom_bars(), atr=4.0)
    for lv in st.levels:
        assert lv.basis
        assert str(round(lv.price, 2))[:2] in lv.basis or f"{lv.price:.4g}" in lv.basis


def test_zones_have_width_so_stops_can_clear_them():
    st = build_structure(_triple_bottom_bars(), atr=4.0)
    multi = [lv for lv in st.levels if lv.touches > 1]
    assert multi, "expected at least one multi-touch zone"
    assert any(lv.width > 0 for lv in multi)


def test_no_atr_or_no_bars_yields_no_structure():
    assert build_structure([], atr=4.0).levels == []
    assert build_structure(_triple_bottom_bars(), atr=None).levels == []
    assert build_structure(_triple_bottom_bars(), atr=0).levels == []


# --- queries ------------------------------------------------------------

def test_nearest_support_is_below_price_and_next_resistance_above():
    st = build_structure(_triple_bottom_bars(), atr=4.0)
    sup = nearest_support(st, 90)
    res = next_resistance(st, 90)
    assert sup is None or sup.price <= 90
    assert res is None or res.price >= 90


def test_min_distance_skips_a_target_too_close_to_pay_for_its_risk():
    st = build_structure(_triple_bottom_bars(), atr=4.0)
    far = next_resistance(st, 90, min_distance=1000)
    assert far is None

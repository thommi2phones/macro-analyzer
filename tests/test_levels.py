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


# ---------------------------------------------------------------------------
# v2 — structure + trusted-voice fusion
# ---------------------------------------------------------------------------

from types import SimpleNamespace  # noqa: E402

from macro_positioning.prices.structure import Level, StructureMap  # noqa: E402


def _feats(close=100.0, atr=4.0, **kw):
    base = {"close": close, "atr14": atr, "n_bars": 200}
    base.update(kw)
    return base


def _zone(price, kind, *, low=None, high=None, strength=0.8, touches=3):
    return Level(
        price=price, low=low if low is not None else price - 0.5,
        high=high if high is not None else price + 0.5,
        kind=kind, touches=touches, last_touch_bars=10, span_bars=60,
        strength=strength, basis=f"{kind} {price:.4g}, held {touches}×",
    )


def _consensus(price, *, trusted=True, win=0.8, name="OG Whales"):
    contributor = SimpleNamespace(
        author_id=name.lower(), display_name=name, price=price, weight=0.7,
        setup_win_rate=win, meaningful=trusted, n_calls=60, conviction=4.0,
        at="2026-08-22 09:00", thesis=None, chart_url=None,
        __dict__={"display_name": name, "setup_win_rate": win,
                  "meaningful": trusted, "at": "2026-08-22 09:00"},
    )
    return SimpleNamespace(
        price=price, weight=0.7, contributors=[contributor], trusted=trusted,
        basis=f"{name} ({int(win * 100)}% setup win over 60 calls)",
    )


def _kol(entry=None, stop=None, target=None):
    return SimpleNamespace(
        entry=entry, stop=stop, target=target, n_signals=3, side="LONG",
    )


# --- structure drives the rails ----------------------------------------

def test_target_comes_from_the_next_supply_zone_not_an_r_multiple():
    st = StructureMap(supports=[_zone(94, "support")], resistances=[_zone(118, "resistance")])
    ls, _ = synthesize_levels(_feats(), side="LONG", structure=st)
    assert ls.target == 118 - 0.5, "sell into the near edge of the zone"
    assert ls.version == "v2"
    target_row = next(p for p in ls.provenance if p["role"] == "target")
    assert target_row["source"] == "structure"
    assert "held 3×" in target_row["basis"]


def test_stop_clears_the_far_edge_of_the_support_zone():
    st = StructureMap(supports=[_zone(96, "support", low=95.0, high=97.0)], resistances=[])
    ls, _ = synthesize_levels(_feats(), side="LONG", structure=st)
    assert ls.stop < 95.0, "a stop inside the zone gets hit by noise"
    assert ls.structural is True


def test_no_overhead_structure_says_open_field_rather_than_faking_a_level():
    """A name at all-time highs has nothing above it. The R-multiple is
    fine there — pretending it's an observed level is not."""
    st = StructureMap(supports=[_zone(94, "support")], resistances=[])
    ls, _ = synthesize_levels(_feats(), side="LONG", structure=st)
    target_row = next(p for p in ls.provenance if p["role"] == "target")
    assert target_row["source"] == "open_field"
    assert "no supply zone in range" in target_row["basis"]


def test_a_wisp_of_resistance_is_not_a_target():
    weak = StructureMap(supports=[_zone(94, "support")],
                        resistances=[_zone(118, "resistance", strength=0.05)])
    ls, _ = synthesize_levels(_feats(), side="LONG", structure=weak)
    assert next(p for p in ls.provenance if p["role"] == "target")["source"] == "open_field"


# --- the gates on borrowed levels --------------------------------------

def test_a_target_behind_price_is_refused_as_already_played_out():
    ls, _ = synthesize_levels(_feats(), side="LONG", kol=_kol(target=_consensus(80)))
    assert not any(p["role"] == "target" and p["source"] == "trusted_voices"
                   for p in ls.provenance)
    assert any("already played out" in r["reason"] for r in ls.rejected)


def test_a_stop_on_the_wrong_side_of_price_is_refused():
    ls, _ = synthesize_levels(_feats(), side="LONG", kol=_kol(stop=_consensus(120)))
    assert any("wrong side of price" in r["reason"] for r in ls.rejected)


def test_a_level_from_a_different_price_regime_is_refused():
    ls, _ = synthesize_levels(_feats(), side="LONG", kol=_kol(target=_consensus(900)))
    assert any("different regime" in r["reason"] for r in ls.rejected)


def test_a_human_stop_implying_untradeable_risk_is_refused():
    """0.1 ATR of risk is noise, not invalidation."""
    ls, _ = synthesize_levels(_feats(), side="LONG", kol=_kol(stop=_consensus(99.6)))
    assert any("outside the tradeable band" in r["reason"] for r in ls.rejected)


def test_refusals_are_recorded_rather_than_silently_dropped():
    ls, _ = synthesize_levels(_feats(), side="LONG", kol=_kol(target=_consensus(80)))
    assert ls.rejected and ls.rejected[0]["who"], "a refusal must name whose level it was"


# --- how structure and humans combine ----------------------------------

def test_a_trusted_target_is_used_when_the_chart_offers_nothing():
    st = StructureMap(supports=[_zone(94, "support")], resistances=[])
    ls, _ = synthesize_levels(_feats(), side="LONG", structure=st,
                              kol=_kol(target=_consensus(130)))
    row = next(p for p in ls.provenance if p["role"] == "target")
    assert row["source"] == "trusted_voices"
    assert ls.target == 130
    assert "OG Whales" in row["basis"]


def test_a_nearer_human_target_wins_over_a_further_zone():
    """Taking profit before the chart says to is the conservative error."""
    st = StructureMap(supports=[_zone(94, "support")], resistances=[_zone(140, "resistance")])
    ls, _ = synthesize_levels(_feats(), side="LONG", structure=st,
                              kol=_kol(target=_consensus(120)))
    assert ls.target == 120
    assert next(p for p in ls.provenance if p["role"] == "target")["source"] == "trusted_voices"


def test_a_further_human_target_does_not_override_the_zone():
    st = StructureMap(supports=[_zone(94, "support")], resistances=[_zone(118, "resistance")])
    # 130 is inside the distance gate (7.5 ATR) but beyond the zone, so
    # it survives as a cross-check instead of moving the target.
    ls, _ = synthesize_levels(_feats(), side="LONG", structure=st,
                              kol=_kol(target=_consensus(130)))
    assert next(p for p in ls.provenance if p["role"] == "target")["source"] == "structure"
    check = next(p for p in ls.provenance if p["role"] == "target_crosscheck")
    assert check["basis"] == "reaches beyond the zone"


def test_structure_keeps_the_stop_and_the_human_becomes_corroboration():
    st = StructureMap(supports=[_zone(96, "support", low=95.0, high=97.0)], resistances=[])
    ls, _ = synthesize_levels(_feats(), side="LONG", structure=st,
                              kol=_kol(stop=_consensus(94.6)))
    assert next(p for p in ls.provenance if p["role"] == "stop")["source"] == "structure"
    assert any(p["role"] == "stop_crosscheck" for p in ls.provenance)


def test_every_rail_carries_a_reason():
    st = StructureMap(supports=[_zone(94, "support")], resistances=[_zone(118, "resistance")])
    ls, _ = synthesize_levels(_feats(), side="LONG", structure=st,
                              kol=_kol(entry=_consensus(99)))
    for role in ("entry", "stop", "target"):
        row = next(p for p in ls.provenance if p["role"] == role)
        assert row["basis"], f"{role} has no stated basis"
        assert row["source"]


def test_v1_behaviour_is_unchanged_without_context():
    """Callers with only bars must still get levels."""
    ls, _ = synthesize_levels(_feats())
    assert ls.version == "v1"
    assert ls.provenance == []

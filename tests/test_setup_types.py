"""Setup-type classifier — detector × asset → framework vocabulary."""

import pytest

from macro_brain.agents.regime_classifier.classifier import PREFERRED_SETUPS
from macro_positioning.scoring.setup_types import classify_setup_type

VOCABULARY = set().union(*PREFERRED_SETUPS.values())


def _c(**kw):
    base = dict(
        method="breakout_20d",
        structural=True,
        side="LONG",
        ticker="AAPL",
        asset_class="equity",
        themes=[],
        rs_features=None,
        regime=None,
    )
    base.update(kw)
    return classify_setup_type(**base)


# --- the contract that makes the score meaningful -----------------------

def test_every_output_exists_in_the_framework_vocabulary():
    """A name outside PREFERRED_SETUPS can never match any regime, so it
    would silently score 0.3 forever."""
    cases = [
        _c(),
        _c(method="pullback_support"),
        _c(method="breakdown_20d"),
        _c(method="rally_resistance", side="SHORT"),
        _c(method="mechanical_v0", structural=False),
        _c(method=None, structural=False),
        _c(asset_class="bond"),
        _c(asset_class="cash_equivalent"),
        _c(ticker="CCJ", themes=["uranium"]),
        _c(ticker="GDX", themes=["precious_metals"]),
        _c(ticker="BTC", asset_class="crypto", themes=["crypto"]),
        _c(ticker="XOP", asset_class="commodity_equity", themes=["energy"]),
    ]
    for got in cases:
        assert got in VOCABULARY, got


def test_no_structure_never_claims_a_regime_preferred_setup():
    """Mechanical rails are a placeholder — dressing them as a preferred
    setup would hand 15 points to assets with no entry."""
    got = _c(method="mechanical_v0", structural=False, themes=["uranium"])
    assert got == "watchlist_building"
    assert got not in PREFERRED_SETUPS["commodity_led_inflation"]


def test_missing_levels_are_watchlist_building():
    assert _c(method=None, structural=False) == "watchlist_building"


# --- theme specialisation ----------------------------------------------

def test_uranium_breakout_is_the_commodity_regimes_own_setup():
    got = _c(ticker="CCJ", themes=["uranium"], asset_class="commodity_and_miners")
    assert got == "uranium_accumulation"
    assert got in PREFERRED_SETUPS["commodity_led_inflation"]


def test_precious_metals_breakout():
    assert _c(ticker="GDX", themes=["precious_metals"]) == "precious_metals_continuation"


def test_crypto_breakout_is_a_hard_asset_breakout():
    got = _c(ticker="BTC", asset_class="crypto", themes=["crypto"])
    assert got == "hard_asset_breakout"
    assert got in PREFERRED_SETUPS["monetary_debasement_hard_asset"]


def test_energy_equity_breakout_is_a_commodity_breakout():
    assert _c(ticker="XOP", asset_class="commodity_equity", themes=["energy"]) == "commodity_breakout"


def test_plain_equity_breakout_stays_generic():
    assert _c(ticker="MSFT", themes=["technology_ai"]) == "breakout_continuation"


# --- side ---------------------------------------------------------------

@pytest.mark.parametrize("method,side", [
    ("breakdown_20d", "SHORT"),
    ("rally_resistance", "SHORT"),
    ("breakout_20d", "SHORT"),
])
def test_short_side_keeps_the_risk_off_vocabulary(method, side):
    """A breakdown in a bullish regime is still a breakdown."""
    got = _c(method=method, side=side, themes=["uranium"])
    assert got == "failed_breakout_short"
    assert got in PREFERRED_SETUPS["risk_off_contraction"]


# --- pullbacks ----------------------------------------------------------

def test_leading_miner_pullback_is_miner_relative_strength():
    got = _c(
        method="pullback_support", ticker="GDX", themes=[],
        asset_class="commodity_and_miners",
        rs_features={"ticker_pct20d": 0.10, "benchmark_pct20d": 0.02},
    )
    assert got == "miner_relative_strength"


def test_lagging_miner_pullback_is_not_relative_strength():
    got = _c(
        method="pullback_support", ticker="GDX", themes=[],
        asset_class="commodity_and_miners",
        rs_features={"ticker_pct20d": 0.01, "benchmark_pct20d": 0.05},
    )
    assert got == "pullback_to_support"


def test_crypto_pullback_is_a_scarcity_asset_pullback():
    got = _c(method="pullback_support", ticker="ETH", asset_class="crypto", themes=["crypto"])
    assert got == "scarcity_asset_pullback"


def test_leading_equity_pullback_reads_as_relative_strength():
    got = _c(
        method="pullback_support", ticker="MSFT",
        rs_features={"ticker_pct20d": 0.09, "benchmark_pct20d": 0.03},
    )
    assert got == "relative_strength_continuation"


# --- non-setups ---------------------------------------------------------

@pytest.mark.parametrize("asset_class", ["bond", "cash_equivalent"])
def test_cash_and_bonds_are_preservation_not_setups(asset_class):
    assert _c(asset_class=asset_class) == "cash_preservation"


# --- regime-aware naming among faithful synonyms ------------------------

def test_pullback_takes_the_chop_vocabulary_in_chop():
    """A defended-level entry is both a pullback and a support retest.
    In chop the framework prefers the retest, so a real setup can score
    instead of losing to 'no setup at all'."""
    got = _c(method="pullback_support", regime="transitional_chop")
    assert got == "support_retest"
    assert got in PREFERRED_SETUPS["transitional_chop"]


def test_same_pullback_takes_the_risk_on_vocabulary_in_expansion():
    got = _c(method="pullback_support", regime="risk_on_expansion")
    assert got == "pullback_to_support"
    assert got in PREFERRED_SETUPS["risk_on_expansion"]


def test_breakout_is_never_renamed_into_a_chop_setup():
    """There is no honest chop synonym for a breakout — it should score
    the non-preferred 0.3 rather than borrow a preferred name."""
    got = _c(method="breakout_20d", regime="transitional_chop")
    assert got == "breakout_continuation"
    assert got not in PREFERRED_SETUPS["transitional_chop"]


def test_theme_specialisation_wins_when_the_regime_prefers_it():
    got = _c(method="pullback_support", ticker="CCJ", themes=["uranium"],
             regime="commodity_led_inflation")
    assert got == "uranium_accumulation"


def test_theme_name_yields_to_the_regime_synonym_when_it_does_not_match():
    """A uranium pullback in chop: uranium_accumulation isn't preferred
    there, support_retest is — and both describe it honestly."""
    got = _c(method="pullback_support", ticker="CCJ", themes=["uranium"],
             regime="transitional_chop")
    assert got == "support_retest"


def test_no_regime_falls_back_to_the_most_specific_name():
    assert _c(method="pullback_support", ticker="CCJ", themes=["uranium"]) == "uranium_accumulation"

"""Tests for macro_indicators: growth/inflation quadrant, FCI, EPU risk."""
from __future__ import annotations

from macro_positioning.core.models import MarketObservation
from macro_positioning.market.macro_indicators import (
    FCIResult,
    GrowthInflationQuadrant,
    EPURisk,
    CotMarketSignal,
    CotPositioning,
    classify_growth_inflation_quadrant,
    compute_fci,
    compute_geopolitical_risk,
    compute_cot_positioning,
    format_prompt_blocks,
)
from macro_positioning.market.cot_provider import CotWeeklyReading


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _obs(metric: str, value: str) -> MarketObservation:
    return MarketObservation(
        observation_id=f"test-{metric}",
        market="test",
        metric=metric,
        value=value,
    )


# ---------------------------------------------------------------------------
# Growth / Inflation Quadrant
# ---------------------------------------------------------------------------

class TestGrowthInflationQuadrant:
    def test_boom(self):
        obs = [_obs("A191RL1Q225SBEA", "3.2"), _obs("T10YIE", "3.5")]
        result = classify_growth_inflation_quadrant(obs)
        assert result.quadrant == "boom"
        assert result.growth_signal == "expanding"
        assert result.inflation_signal == "elevated"
        assert result.confidence > 0.5

    def test_stagflation(self):
        obs = [_obs("A191RL1Q225SBEA", "-0.5"), _obs("T10YIE", "3.2")]
        result = classify_growth_inflation_quadrant(obs)
        assert result.quadrant == "stagflation"
        assert result.growth_signal == "contracting"
        assert result.inflation_signal == "elevated"

    def test_deflation(self):
        obs = [_obs("A191RL1Q225SBEA", "-1.0"), _obs("T10YIE", "1.5")]
        result = classify_growth_inflation_quadrant(obs)
        assert result.quadrant == "deflation"
        assert result.growth_signal == "contracting"
        assert result.inflation_signal == "subdued"

    def test_goldilocks(self):
        obs = [_obs("A191RL1Q225SBEA", "2.8"), _obs("T10YIE", "1.8")]
        result = classify_growth_inflation_quadrant(obs)
        assert result.quadrant == "goldilocks"
        assert result.growth_signal == "expanding"
        assert result.inflation_signal == "subdued"

    def test_transitional_on_stable_growth(self):
        obs = [_obs("A191RL1Q225SBEA", "1.5"), _obs("T10YIE", "3.5")]
        result = classify_growth_inflation_quadrant(obs)
        assert result.quadrant == "transitional"

    def test_transitional_on_moderate_inflation(self):
        obs = [_obs("A191RL1Q225SBEA", "2.8"), _obs("T10YIE", "2.5")]
        result = classify_growth_inflation_quadrant(obs)
        assert result.quadrant == "transitional"

    def test_empty_observations_returns_default(self):
        result = classify_growth_inflation_quadrant([])
        assert result.quadrant == "transitional"
        assert result.confidence < 0.5

    def test_fallback_to_indpro_when_gdp_absent(self):
        obs = [_obs("INDPRO", "104.0"), _obs("T10YIE", "3.5")]
        result = classify_growth_inflation_quadrant(obs)
        assert result.growth_series_used == "INDPRO"
        assert result.growth_signal == "expanding"

    def test_summary_is_non_empty(self):
        obs = [_obs("A191RL1Q225SBEA", "3.0"), _obs("T10YIE", "3.0")]
        result = classify_growth_inflation_quadrant(obs)
        assert len(result.summary) > 20


# ---------------------------------------------------------------------------
# Financial Conditions Index
# ---------------------------------------------------------------------------

class TestFCI:
    def test_tightening_from_nfci(self):
        obs = [_obs("NFCI", "0.5")]
        result = compute_fci(obs)
        assert result.label == "tightening"
        assert result.score > 0.3
        assert result.primary_driver == "NFCI"

    def test_easing_from_nfci(self):
        obs = [_obs("NFCI", "-0.6")]
        result = compute_fci(obs)
        assert result.label == "easing"
        assert result.score < -0.3

    def test_neutral_from_nfci(self):
        obs = [_obs("NFCI", "0.1")]
        result = compute_fci(obs)
        assert result.label == "neutral"

    def test_empty_observations_returns_neutral(self):
        result = compute_fci([])
        assert result.label == "neutral"
        assert result.primary_driver == "unavailable"

    def test_components_populated(self):
        obs = [_obs("NFCI", "0.4"), _obs("ANFCI", "0.3"), _obs("VIXCLS", "30.0")]
        result = compute_fci(obs)
        assert "NFCI" in result.components
        assert "ANFCI" in result.components
        assert "VIXCLS" in result.components

    def test_fallback_to_sub_indicators_when_nfci_absent(self):
        # VIX at 30 (neutral=20, scale=0.05) → normalised = +0.5 → tightening
        obs = [_obs("VIXCLS", "30.0")]
        result = compute_fci(obs)
        assert result.score > 0.0


# ---------------------------------------------------------------------------
# Geopolitical / EPU Risk
# ---------------------------------------------------------------------------

class TestEPURisk:
    def test_elevated_epu(self):
        obs = [
            _obs("USEPUINDXD", "200.0"),
            _obs("GEPUCURRENT", "180.0"),
            _obs("EPUTRADE", "160.0"),
        ]
        result = compute_geopolitical_risk(obs)
        assert result.level == "elevated"
        assert result.composite_score > 150

    def test_low_epu(self):
        obs = [
            _obs("USEPUINDXD", "70.0"),
            _obs("GEPUCURRENT", "65.0"),
        ]
        result = compute_geopolitical_risk(obs)
        assert result.level == "low"
        assert result.composite_score < 80

    def test_moderate_epu(self):
        obs = [
            _obs("USEPUINDXD", "110.0"),
            _obs("GEPUCURRENT", "105.0"),
        ]
        result = compute_geopolitical_risk(obs)
        assert result.level == "moderate"

    def test_empty_observations_returns_moderate_default(self):
        result = compute_geopolitical_risk([])
        assert result.level == "moderate"
        assert result.composite_score == 100.0
        assert result.dominant_driver == "unavailable"

    def test_dominant_driver_is_highest_deviation(self):
        obs = [
            _obs("USEPUINDXD", "105.0"),   # deviation 5
            _obs("EPUTRADE", "180.0"),      # deviation 80 ← dominant
            _obs("EPUMONETARY", "95.0"),    # deviation 5
        ]
        result = compute_geopolitical_risk(obs)
        assert result.dominant_driver == "EPUTRADE"

    def test_components_populated(self):
        obs = [_obs("USEPUINDXD", "120.0"), _obs("GEPUCURRENT", "130.0")]
        result = compute_geopolitical_risk(obs)
        assert "USEPUINDXD" in result.components
        assert "GEPUCURRENT" in result.components


# ---------------------------------------------------------------------------
# format_prompt_blocks convenience wrapper
# ---------------------------------------------------------------------------

class TestFormatPromptBlocks:
    def test_empty_returns_dashes(self):
        q, f, e, c = format_prompt_blocks([])
        assert q == "—"
        assert f == "—"
        assert e == "—"
        assert c == "—"

    def test_non_empty_returns_strings(self):
        obs = [
            _obs("A191RL1Q225SBEA", "2.8"),
            _obs("T10YIE", "3.2"),
            _obs("NFCI", "0.2"),
            _obs("USEPUINDXD", "130.0"),
        ]
        q, f, e, c = format_prompt_blocks(obs)
        assert "QUADRANT" in q.upper() or "quadrant" in q.lower() or "BOOM" in q.upper() or len(q) > 10
        assert "FCI" in f or "score" in f.lower() or len(f) > 10
        assert "EPU" in e or "composite" in e.lower() or len(e) > 10

    def test_cot_block_populated_when_readings_provided(self):
        from datetime import date
        readings = [
            CotWeeklyReading(
                market="Gold", cftc_name="GOLD - 100 TROY OUNCES",
                report_date=date(2025, 1, 3),
                noncomm_long=180000, noncomm_short=80000,
                noncomm_net=100000, open_interest=500000,
                net_pct_oi=20.0,
            )
        ]
        obs = [_obs("NFCI", "0.1")]
        q, f, e, c = format_prompt_blocks(obs, cot_readings=readings)
        assert "Gold" in c
        assert len(c) > 5


# ---------------------------------------------------------------------------
# COT positioning classifier
# ---------------------------------------------------------------------------

def _cot_reading(market: str, report_date_str: str, net_pct_oi: float, oi: int = 100000) -> CotWeeklyReading:
    from datetime import date
    d = date.fromisoformat(report_date_str)
    nc_net = int(net_pct_oi / 100 * oi)
    return CotWeeklyReading(
        market=market, cftc_name=market,
        report_date=d,
        noncomm_long=max(0, nc_net), noncomm_short=max(0, -nc_net),
        noncomm_net=nc_net, open_interest=oi,
        net_pct_oi=net_pct_oi,
    )


class TestCotPositioning:
    def test_empty_readings_returns_empty(self):
        result = compute_cot_positioning([])
        assert result.markets == []
        assert result.extremes == []
        assert result.as_of is None

    def test_single_reading_no_zscore(self):
        r = _cot_reading("Gold", "2025-01-03", 20.0)
        result = compute_cot_positioning([r])
        assert len(result.markets) == 1
        sig = result.markets[0]
        assert sig.market == "Gold"
        assert sig.z_score is None  # only 1 data point, can't compute z
        # net_pct_oi=20 ≥ 20 → elevated via absolute fallback
        assert sig.signal == "elevated"

    def test_extreme_long_z_score(self):
        # History alternates 3/7 (mean=5, std≈2); spike to 40 → z≈17.5
        history = [
            _cot_reading("Crude Oil (WTI)", f"2025-01-{i+1:02d}", 3.0 if i % 2 == 0 else 7.0)
            for i in range(20)
        ]
        spike = _cot_reading("Crude Oil (WTI)", "2025-02-01", 40.0)
        result = compute_cot_positioning(history + [spike])
        crude = next(s for s in result.markets if s.market == "Crude Oil (WTI)")
        assert crude.z_score is not None
        assert crude.z_score > 2.0
        assert crude.signal == "extreme_long"

    def test_extreme_short_z_score(self):
        # History alternates -1/-3 (mean=-2, std≈1); spike to -35 → z≈-33
        history = [
            _cot_reading("EUR/USD", f"2025-01-{i+1:02d}", -1.0 if i % 2 == 0 else -3.0)
            for i in range(20)
        ]
        spike = _cot_reading("EUR/USD", "2025-02-01", -35.0)
        result = compute_cot_positioning(history + [spike])
        eur = next(s for s in result.markets if s.market == "EUR/USD")
        assert eur.signal == "extreme_short"

    def test_neutral_not_in_extremes(self):
        readings = [_cot_reading("Gold", f"2025-01-{i+1:02d}", 5.0) for i in range(20)]
        result = compute_cot_positioning(readings)
        assert result.extremes == []

    def test_extremes_list_populated(self):
        # Use varying history so z-score is computable; spike well above 2σ
        history = [
            _cot_reading("Gold", f"2025-01-{i+1:02d}", 3.0 if i % 2 == 0 else 7.0)
            for i in range(20)
        ]
        spike = _cot_reading("Gold", "2025-02-01", 40.0)
        result = compute_cot_positioning(history + [spike])
        assert len(result.extremes) >= 1

    def test_as_of_is_latest_date(self):
        from datetime import date
        readings = [
            _cot_reading("Gold", "2025-01-10", 10.0),
            _cot_reading("Gold", "2025-01-17", 12.0),
            _cot_reading("Gold", "2025-01-24", 11.0),
        ]
        result = compute_cot_positioning(readings)
        assert result.as_of == date(2025, 1, 24)

    def test_summary_non_empty(self):
        r = _cot_reading("Gold", "2025-01-03", 5.0)
        result = compute_cot_positioning([r])
        assert len(result.summary) > 10

    def test_fred_source_tag_lookup(self):
        from macro_positioning.core.models import MarketObservation
        from macro_positioning.market.macro_indicators import _find_value
        # Simulate a real FRED observation (source tagged, value includes unit)
        obs = MarketObservation(
            observation_id="test-fred",
            market="growth",
            metric="Real GDP QoQ Annualised",
            value="2.5 %",
            source="FRED:A191RL1Q225SBEA",
        )
        result = _find_value([obs], "A191RL1Q225SBEA")
        assert result == 2.5

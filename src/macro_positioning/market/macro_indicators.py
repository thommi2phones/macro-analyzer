"""Structured macro indicator classifiers.

Three pure functions that consume the existing FRED MarketObservation list
and return structured, named results — ready for both LLM prompt injection
and dashboard display.

All functions gracefully degrade: if the relevant FRED series are absent from
the observations (API unavailable, series not fetched), they fall back to a
neutral/moderate default rather than raising.
"""

from __future__ import annotations

import math
from datetime import date
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from macro_positioning.core.models import MarketObservation

if TYPE_CHECKING:
    from macro_positioning.market.cot_provider import CotWeeklyReading


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_value(observations: list[MarketObservation], series_id: str) -> float | None:
    """Return the float value of the first observation matching series_id.

    Matches on either:
    - obs.metric == series_id  (test-style: metric IS the series ID)
    - obs.source == f"FRED:{series_id}"  (real FRED observations tagged by source)

    FRED values include units (e.g. "2.5 %") — only the numeric part is parsed.
    """
    for obs in observations:
        if obs.metric == series_id or obs.source == f"FRED:{series_id}":
            try:
                raw = (obs.value or "").split()[0].replace(",", "")
                return float(raw)
            except (ValueError, TypeError):
                return None
    return None


# ---------------------------------------------------------------------------
# 1. Growth / Inflation Quadrant
# ---------------------------------------------------------------------------

class GrowthInflationQuadrant(BaseModel):
    quadrant: Literal["boom", "stagflation", "deflation", "goldilocks", "transitional"]
    growth_signal: Literal["expanding", "stable", "contracting"]
    inflation_signal: Literal["elevated", "moderate", "subdued"]
    confidence: float
    summary: str
    growth_series_used: str
    inflation_series_used: str


def classify_growth_inflation_quadrant(
    observations: list[MarketObservation],
) -> GrowthInflationQuadrant:
    """Classify the current macro regime into one of four quadrants.

    Growth axis: A191RL1Q225SBEA (Real GDP QoQ %) → fallback INDPRO level signal.
    Inflation axis: T10YIE (10Y breakeven %) → fallback CPIAUCSL absolute level.

    Thresholds:
      GDP > 2.5% → expanding | 0–2.5% → stable | < 0% → contracting
      T10YIE > 3.0% → elevated | 2.0–3.0% → moderate | < 2.0% → subdued

    Quadrant matrix (expanding/contracting × elevated/subdued):
      expanding + elevated   = boom
      contracting + elevated = stagflation
      contracting + subdued  = deflation
      expanding + subdued    = goldilocks
      any "stable" axis      = transitional
    """
    # --- Growth signal ---
    gdp = _find_value(observations, "A191RL1Q225SBEA")
    growth_series = "A191RL1Q225SBEA"

    if gdp is not None:
        if gdp > 2.5:
            growth_signal: Literal["expanding", "stable", "contracting"] = "expanding"
        elif gdp < 0.0:
            growth_signal = "contracting"
        else:
            growth_signal = "stable"
        growth_conf = 0.85
    else:
        # Fallback: INDPRO — level > 102 = expansion territory (post-2020 avg)
        indpro = _find_value(observations, "INDPRO")
        growth_series = "INDPRO"
        if indpro is not None:
            if indpro > 103:
                growth_signal = "expanding"
            elif indpro < 99:
                growth_signal = "contracting"
            else:
                growth_signal = "stable"
            growth_conf = 0.55  # less reliable without rate-of-change
        else:
            growth_signal = "stable"
            growth_conf = 0.30
            growth_series = "unavailable"

    # --- Inflation signal ---
    t10yie = _find_value(observations, "T10YIE")
    inflation_series = "T10YIE"

    if t10yie is not None:
        if t10yie > 3.0:
            inflation_signal: Literal["elevated", "moderate", "subdued"] = "elevated"
        elif t10yie < 2.0:
            inflation_signal = "subdued"
        else:
            inflation_signal = "moderate"
        infl_conf = 0.85
    else:
        # Fallback: CPIAUCSL absolute index level vs historical threshold
        cpi = _find_value(observations, "CPIAUCSL")
        inflation_series = "CPIAUCSL"
        if cpi is not None:
            # CPI index level 300+ = post-2022 elevated; rough threshold
            if cpi > 310:
                inflation_signal = "elevated"
            elif cpi < 270:
                inflation_signal = "subdued"
            else:
                inflation_signal = "moderate"
            infl_conf = 0.45  # absolute level less meaningful without YoY
        else:
            inflation_signal = "moderate"
            infl_conf = 0.30
            inflation_series = "unavailable"

    # --- Quadrant mapping ---
    if growth_signal == "stable" or inflation_signal == "moderate":
        quadrant: Literal["boom", "stagflation", "deflation", "goldilocks", "transitional"] = "transitional"
    elif growth_signal == "expanding" and inflation_signal == "elevated":
        quadrant = "boom"
    elif growth_signal == "contracting" and inflation_signal == "elevated":
        quadrant = "stagflation"
    elif growth_signal == "contracting" and inflation_signal == "subdued":
        quadrant = "deflation"
    else:  # expanding + subdued
        quadrant = "goldilocks"

    confidence = round((growth_conf + infl_conf) / 2, 2)

    _QUADRANT_SUMMARIES = {
        "boom": "Expanding growth with elevated inflation. Risk assets broadly supported; commodities and short-duration outperform.",
        "stagflation": "Contracting growth with persistent inflation. Real assets, commodities, and inflation-linked bonds defensive; equities under pressure.",
        "deflation": "Growth contraction with subdued inflation. Duration assets (long bonds) favoured; risk assets vulnerable.",
        "goldilocks": "Expanding growth with subdued inflation. Broad risk-on environment; equities lead, commodities lag.",
        "transitional": "Mixed signals — growth and/or inflation in transition zone. Reduced conviction; monitor for confirmation.",
    }

    return GrowthInflationQuadrant(
        quadrant=quadrant,
        growth_signal=growth_signal,
        inflation_signal=inflation_signal,
        confidence=confidence,
        summary=_QUADRANT_SUMMARIES[quadrant],
        growth_series_used=growth_series,
        inflation_series_used=inflation_series,
    )


# ---------------------------------------------------------------------------
# 2. Financial Conditions Index
# ---------------------------------------------------------------------------

class FCIResult(BaseModel):
    score: float          # NFCI convention: positive = tighter, negative = easier
    label: Literal["tightening", "neutral", "easing"]
    primary_driver: str   # series ID with highest absolute deviation from 0
    components: dict[str, float]
    summary: str


# Normalisation scales for raw sub-indicators to approximate NFCI units
# VIX: 20 = neutral, each 10 pts ≈ +0.5 NFCI units
# TED spread: 0.5% = neutral, each 0.5% ≈ +0.3 NFCI units
# HY OAS: 400bps = neutral, each 200bps ≈ +0.4 NFCI units
_FCI_NORMALISE: dict[str, tuple[float, float]] = {
    # series: (neutral_level, scale_factor → NFCI units)
    "VIXCLS":       (20.0,  0.05),
    "TEDRATE":      (0.5,   0.60),
    "BAMLH0A0HYM2": (4.0,   0.20),
}


def compute_fci(observations: list[MarketObservation]) -> FCIResult:
    """Compute a Financial Conditions Index score.

    Primary: NFCI (Chicago Fed) — already a composite on NFCI scale.
    If absent: average normalised scores from ANFCI, STLFSI4, VIX, TED, HY OAS.

    NFCI > +0.3 = tightening | NFCI < -0.3 = easing | else neutral.
    """
    components: dict[str, float] = {}

    nfci = _find_value(observations, "NFCI")
    if nfci is not None:
        components["NFCI"] = round(nfci, 4)

    for sid in ("ANFCI", "STLFSI4"):
        v = _find_value(observations, sid)
        if v is not None:
            components[sid] = round(v, 4)

    for sid, (neutral, scale) in _FCI_NORMALISE.items():
        v = _find_value(observations, sid)
        if v is not None:
            normalised = (v - neutral) * scale
            components[sid] = round(normalised, 4)

    if not components:
        return FCIResult(
            score=0.0,
            label="neutral",
            primary_driver="unavailable",
            components={},
            summary="Financial conditions data unavailable; defaulting to neutral.",
        )

    # Use NFCI as primary if available, else average all normalised components
    if "NFCI" in components:
        score = components["NFCI"]
    else:
        score = sum(components.values()) / len(components)

    score = round(score, 4)

    if score > 0.3:
        label: Literal["tightening", "neutral", "easing"] = "tightening"
    elif score < -0.3:
        label = "easing"
    else:
        label = "neutral"

    # Primary driver: component with highest absolute deviation from 0
    primary_driver = max(components, key=lambda k: abs(components[k]))

    _FCI_SUMMARIES = {
        "tightening": (
            f"Financial conditions are restrictive (score {score:+.3f}). "
            "Credit spreads / volatility elevated; headwind for risk assets and credit."
        ),
        "neutral": (
            f"Financial conditions are broadly neutral (score {score:+.3f}). "
            "No systemic stress signal; monitor for direction change."
        ),
        "easing": (
            f"Financial conditions are accommodative (score {score:+.3f}). "
            "Liquidity supportive for risk assets; watch for leverage build-up."
        ),
    }

    return FCIResult(
        score=score,
        label=label,
        primary_driver=primary_driver,
        components=components,
        summary=_FCI_SUMMARIES[label],
    )


# ---------------------------------------------------------------------------
# 3. Geopolitical / Policy Risk (EPU)
# ---------------------------------------------------------------------------

class EPURisk(BaseModel):
    composite_score: float    # index units (~100 = historical avg)
    level: Literal["elevated", "moderate", "low"]
    dominant_driver: str      # series ID with highest deviation from 100
    components: dict[str, float]
    summary: str


_EPU_SERIES = (
    "USEPUINDXD",
    "GEPUCURRENT",
    "EPUTRADE",
    "EPUFISCAL",
    "EPUMONETARY",
    "EMVNATSEC",
)

_EPU_LABELS: dict[str, str] = {
    "USEPUINDXD":  "US Policy Uncertainty",
    "GEPUCURRENT": "Global EPU",
    "EPUTRADE":    "Trade Policy",
    "EPUFISCAL":   "Fiscal Policy",
    "EPUMONETARY": "Monetary Policy",
    "EMVNATSEC":   "National Security Vol",
}


def compute_geopolitical_risk(observations: list[MarketObservation]) -> EPURisk:
    """Compute a composite geopolitical / policy risk score from six EPU series.

    EPU indices are normalised to 100 = long-run average.
    Composite > 150 = elevated | < 80 = low | else moderate.
    """
    components: dict[str, float] = {}
    for sid in _EPU_SERIES:
        v = _find_value(observations, sid)
        if v is not None:
            components[sid] = round(v, 1)

    if not components:
        return EPURisk(
            composite_score=100.0,
            level="moderate",
            dominant_driver="unavailable",
            components={},
            summary="Geopolitical risk data unavailable; defaulting to moderate.",
        )

    composite_score = round(sum(components.values()) / len(components), 1)

    if composite_score > 150:
        level: Literal["elevated", "moderate", "low"] = "elevated"
    elif composite_score < 80:
        level = "low"
    else:
        level = "moderate"

    # Dominant driver: series with highest deviation from 100
    dominant_driver = max(components, key=lambda k: abs(components[k] - 100))
    dominant_label = _EPU_LABELS.get(dominant_driver, dominant_driver)

    _LEVEL_SUMMARIES = {
        "elevated": (
            f"Geopolitical and policy risk is elevated (EPU composite {composite_score:.0f}). "
            f"Primary driver: {dominant_label}. "
            "Elevated uncertainty typically compresses risk appetite and supports safe havens (gold, CHF, JPY, long Treasuries)."
        ),
        "moderate": (
            f"Geopolitical risk is moderate (EPU composite {composite_score:.0f}). "
            f"Primary driver: {dominant_label}. "
            "Risk environment broadly manageable; no outsized policy uncertainty premium."
        ),
        "low": (
            f"Geopolitical risk is low (EPU composite {composite_score:.0f}). "
            "Supportive backdrop for risk assets; less safe-haven demand."
        ),
    }

    return EPURisk(
        composite_score=composite_score,
        level=level,
        dominant_driver=dominant_driver,
        components=components,
        summary=_LEVEL_SUMMARIES[level],
    )


# ---------------------------------------------------------------------------
# 4. COT Speculative Positioning
# ---------------------------------------------------------------------------

class CotMarketSignal(BaseModel):
    market: str
    report_date: date
    noncomm_net: int
    net_pct_oi: float
    z_score: float | None
    signal: Literal["extreme_long", "elevated", "neutral", "suppressed", "extreme_short"]


class CotPositioning(BaseModel):
    markets: list[CotMarketSignal]
    extremes: list[CotMarketSignal]  # signal != "neutral"
    as_of: date | None
    summary: str


def _z_score(value: float, history: list[float]) -> float | None:
    if len(history) < 4:
        return None
    mean = sum(history) / len(history)
    variance = sum((x - mean) ** 2 for x in history) / len(history)
    std = math.sqrt(variance)
    if std == 0:
        return None  # zero-variance history; fall back to absolute thresholds
    return round((value - mean) / std, 2)


def _cot_signal(
    net_pct_oi: float,
    z: float | None,
) -> Literal["extreme_long", "elevated", "neutral", "suppressed", "extreme_short"]:
    if z is not None:
        if z >= 2.0:
            return "extreme_long"
        if z >= 1.0:
            return "elevated"
        if z <= -2.0:
            return "extreme_short"
        if z <= -1.0:
            return "suppressed"
        return "neutral"
    # Fallback: absolute pct_oi thresholds when history is thin
    if net_pct_oi >= 20.0:
        return "elevated"
    if net_pct_oi <= -20.0:
        return "suppressed"
    return "neutral"


def compute_cot_positioning(readings: list[CotWeeklyReading]) -> CotPositioning:
    """Classify speculative COT positioning for each market.

    Takes a list of CotWeeklyReading objects (multiple weeks per market).
    For each market: compute z-score of current net_pct_oi vs YTD history
    and classify as extreme_long / elevated / neutral / suppressed / extreme_short.

    Gracefully returns an empty result when readings is empty.
    """
    if not readings:
        return CotPositioning(
            markets=[],
            extremes=[],
            as_of=None,
            summary="COT data unavailable.",
        )

    # Group by market; sort each group by date ascending
    from collections import defaultdict
    by_market: dict[str, list[CotWeeklyReading]] = defaultdict(list)
    for r in readings:
        by_market[r.market].append(r)

    signals: list[CotMarketSignal] = []
    latest_date: date | None = None

    for market, history_list in by_market.items():
        history_list.sort(key=lambda r: r.report_date)
        latest = history_list[-1]

        if latest_date is None or latest.report_date > latest_date:
            latest_date = latest.report_date

        history_pct = [r.net_pct_oi for r in history_list]
        z = _z_score(latest.net_pct_oi, history_pct[:-1])  # exclude current from history
        sig = _cot_signal(latest.net_pct_oi, z)

        signals.append(CotMarketSignal(
            market=market,
            report_date=latest.report_date,
            noncomm_net=latest.noncomm_net,
            net_pct_oi=latest.net_pct_oi,
            z_score=z,
            signal=sig,
        ))

    signals.sort(key=lambda s: (s.signal == "neutral", abs(s.net_pct_oi if s.z_score is None else s.z_score or 0), ), reverse=True)
    extremes = [s for s in signals if s.signal != "neutral"]

    if extremes:
        top = extremes[0]
        direction = "LONG" if top.signal in ("extreme_long", "elevated") else "SHORT"
        summary = (
            f"{len(extremes)} market(s) at positioning extremes as of {latest_date}. "
            f"Most extreme: {top.market} ({top.signal.replace('_', ' ')}, "
            f"net {top.net_pct_oi:+.1f}% of OI"
            + (f", z={top.z_score:+.1f}" if top.z_score is not None else "")
            + f"). Speculators skewed {direction}."
        )
    else:
        summary = (
            f"COT positioning broadly neutral as of {latest_date}. "
            "No markets at significant speculative extremes."
        )

    return CotPositioning(
        markets=signals,
        extremes=extremes,
        as_of=latest_date,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Convenience: format all four as LLM prompt blocks
# ---------------------------------------------------------------------------

def format_prompt_blocks(
    observations: list[MarketObservation],
    cot_readings: list[CotWeeklyReading] | None = None,
) -> tuple[str, str, str, str]:
    """Return (regime_block, fci_block, epu_block, cot_block) for prompt injection.

    If observations is empty all four return '—'.
    cot_readings is optional; if None or empty, cot_block returns '—'.
    """
    if not observations:
        return "—", "—", "—", "—"

    quadrant = classify_growth_inflation_quadrant(observations)
    fci = compute_fci(observations)
    epu = compute_geopolitical_risk(observations)
    cot = compute_cot_positioning(cot_readings or [])

    regime_block = (
        f"Quadrant: {quadrant.quadrant.upper()} | "
        f"Growth: {quadrant.growth_signal} | "
        f"Inflation: {quadrant.inflation_signal} | "
        f"Confidence: {quadrant.confidence:.0%}\n"
        f"{quadrant.summary}"
    )
    fci_block = (
        f"FCI Score: {fci.score:+.3f} ({fci.label.upper()}) | "
        f"Driver: {fci.primary_driver}\n"
        f"{fci.summary}"
    )
    epu_block = (
        f"Composite EPU: {epu.composite_score:.0f} ({epu.level.upper()}) | "
        f"Dominant: {epu.dominant_driver}\n"
        f"{epu.summary}"
    )

    if cot.markets:
        lines = []
        for s in cot.markets[:8]:  # top 8 to avoid bloating the prompt
            z_str = f" z={s.z_score:+.1f}" if s.z_score is not None else ""
            lines.append(f"{s.market}: {s.net_pct_oi:+.1f}% OI ({s.signal.replace('_', ' ')}){z_str}")
        cot_block = "\n".join(lines) + f"\n{cot.summary}"
    else:
        cot_block = "—"

    return regime_block, fci_block, epu_block, cot_block

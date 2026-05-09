"""Technical Scorer — heuristic, no LLM.

Reads `setup.technical_features` (a flat dict produced by
`macro_positioning.prices.technicals.compute_technical_features`) and
emits a SubScore for `technical_structure` per framework §5.

Framework rules (from config/trading_framework.json `market_structure_signals`):
- bullish_structure: higher_highs && higher_lows && support_retests_hold → +12
- bearish_structure: lower_highs && lower_lows && resistance_retests_fail → -12
- neutral_structure: range_bound or trend_unclear → -5

We add MA-position context per framework §5 "Bullish Structure" notes:
- price above 50DMA + 200DMA = strong
- price above 50DMA only = moderate
- price below 50DMA = weak

And recent breakout / breakdown:
- recent_breakout && above_ma50 = +0.1 to value
- recent_breakdown && below_ma50 = -0.1 to value

Output value is 0..1 flat; orchestrator weights to 0..20.
"""

from __future__ import annotations

from macro_brain.types import SetupContext, SubScore


def score_technical_structure(setup: SetupContext) -> SubScore:
    """Score technical structure from features.

    Missing features → neutral 0.5 with note (matches old stub behavior).
    """
    feats = setup.technical_features or {}
    n = feats.get("n_bars") or 0

    if n < 50:
        # Need at least 50 bars for a 50DMA-aware read
        return SubScore(
            component="technical_structure",
            value=0.5,
            contributing_features={"n_bars": float(n)},
            notes=f"Insufficient price history ({n} bars).",
        )

    # Pull features
    higher_highs = bool(feats.get("higher_highs"))
    higher_lows = bool(feats.get("higher_lows"))
    lower_highs = bool(feats.get("lower_highs"))
    lower_lows = bool(feats.get("lower_lows"))
    above_50 = bool(feats.get("above_ma50"))
    above_200 = bool(feats.get("above_ma200"))
    breakout = bool(feats.get("recent_breakout"))
    breakdown = bool(feats.get("recent_breakdown"))
    rsi14 = feats.get("rsi14")

    # Base: structure pattern
    if higher_highs and higher_lows:
        structure_v = 0.85
        note = "Bullish structure (higher highs + higher lows)."
    elif lower_highs and lower_lows:
        structure_v = 0.15
        note = "Bearish structure (lower highs + lower lows)."
    elif higher_highs or higher_lows:
        structure_v = 0.6
        note = "Mixed/improving structure."
    elif lower_highs or lower_lows:
        structure_v = 0.4
        note = "Mixed/deteriorating structure."
    else:
        structure_v = 0.5
        note = "Range-bound / unclear structure."

    # MA position adjustment
    if above_50 and above_200:
        structure_v = min(1.0, structure_v + 0.10)
    elif above_50 and not above_200:
        structure_v = min(1.0, structure_v + 0.03)
    elif not above_50 and above_200:
        structure_v = max(0.0, structure_v - 0.03)
    else:  # below both
        structure_v = max(0.0, structure_v - 0.10)

    # Recent breakout / breakdown nudges
    if breakout and above_50:
        structure_v = min(1.0, structure_v + 0.10)
        note += " Recent breakout above 20-bar high."
    elif breakdown and not above_50:
        structure_v = max(0.0, structure_v - 0.10)
        note += " Recent breakdown below 20-bar low."

    # Overbought / oversold guard — extreme RSI is risk-of-mean-reversion
    rsi_signal = 0.0
    if rsi14 is not None:
        if rsi14 > 80:
            rsi_signal = -0.05
            note += f" RSI {rsi14:.0f} extended."
        elif rsi14 < 20:
            rsi_signal = -0.05
            note += f" RSI {rsi14:.0f} oversold."
        structure_v = max(0.0, min(1.0, structure_v + rsi_signal))

    return SubScore(
        component="technical_structure",
        value=structure_v,
        contributing_features={
            "higher_highs": float(higher_highs),
            "higher_lows": float(higher_lows),
            "lower_highs": float(lower_highs),
            "lower_lows": float(lower_lows),
            "above_ma50": float(above_50),
            "above_ma200": float(above_200),
            "recent_breakout": float(breakout),
            "recent_breakdown": float(breakdown),
            "rsi14": float(rsi14) if rsi14 is not None else 0.0,
            "n_bars": float(n),
        },
        notes=note,
    )

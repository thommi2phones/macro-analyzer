"""Technical Scorer — heuristic, no LLM.

Reads `setup.technical_features` (a flat dict produced by
`macro_positioning.prices.technicals.compute_technical_features`) and
emits a SubScore for `technical_structure` per framework §5.

Framework rules (from config/trading_framework.json `market_structure_signals`):
- bullish_structure: higher_highs && higher_lows && support_retests_hold → +12
- bearish_structure: lower_highs && lower_lows && resistance_retests_fail → -12
- neutral_structure: range_bound or trend_unclear → -5

We layer in:
- MA position (above SMA50 + SMA200 = strong; below both = weak)
- EMA position — recency-weighted; faster signal of trend change.
  Rising sequence (close > EMA20 > EMA50) is a textbook bullish
  alignment per §5.
- Recent breakout / breakdown (20-bar pierce)
- Multi-horizon momentum: 5d (weekly), 20d (monthly), 60d (cycle).
  All-positive momentum stack = strong trend; mixed = mean-reversion
  risk; all-negative = downtrend.
- RSI extremes (>80 or <20) as mean-reversion guards

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
    above_ema20 = bool(feats.get("above_ema20"))
    above_ema50 = bool(feats.get("above_ema50"))
    breakout = bool(feats.get("recent_breakout"))
    breakdown = bool(feats.get("recent_breakdown"))
    rsi14 = feats.get("rsi14")

    pct5 = feats.get("pct_change_5d")    # weekly
    pct20 = feats.get("pct_change_20d")  # monthly
    pct60 = feats.get("pct_change_60d")  # quarterly / cycle

    # ─── Base: structure pattern ──────────────────────────────────────
    if higher_highs and higher_lows:
        structure_v = 0.85
        note = "Bullish structure (HH+HL)."
    elif lower_highs and lower_lows:
        structure_v = 0.15
        note = "Bearish structure (LH+LL)."
    elif higher_highs or higher_lows:
        structure_v = 0.6
        note = "Mixed/improving structure."
    elif lower_highs or lower_lows:
        structure_v = 0.4
        note = "Mixed/deteriorating structure."
    else:
        structure_v = 0.5
        note = "Range-bound."

    # ─── SMA position ─────────────────────────────────────────────────
    if above_50 and above_200:
        structure_v += 0.07
    elif above_50 and not above_200:
        structure_v += 0.02
    elif not above_50 and above_200:
        structure_v -= 0.02
    else:
        structure_v -= 0.07

    # ─── EMA alignment (recency-weighted; faster trend signal) ───────
    if above_ema20 and above_ema50:
        structure_v += 0.05
        note += " Above EMA20+EMA50."
    elif not above_ema20 and not above_ema50:
        structure_v -= 0.05

    # ─── Multi-horizon momentum ──────────────────────────────────────
    momentums = [m for m in (pct5, pct20, pct60) if m is not None]
    if len(momentums) == 3:
        positives = sum(1 for m in momentums if m > 0)
        avg_mom = sum(momentums) / 3
        if positives == 3:
            structure_v += 0.08
            note += f" Momentum stack +++ (avg {avg_mom*100:+.1f}%)."
        elif positives == 0:
            structure_v -= 0.08
            note += f" Momentum stack --- (avg {avg_mom*100:+.1f}%)."
        elif positives == 2:
            structure_v += 0.03
        elif positives == 1:
            structure_v -= 0.03

    # ─── Recent breakout / breakdown ──────────────────────────────────
    if breakout and above_50:
        structure_v += 0.08
        note += " Recent breakout."
    elif breakdown and not above_50:
        structure_v -= 0.08
        note += " Recent breakdown."

    # ─── RSI extremes guard ──────────────────────────────────────────
    if rsi14 is not None:
        if rsi14 > 80:
            structure_v -= 0.05
            note += f" RSI {rsi14:.0f} extended."
        elif rsi14 < 20:
            structure_v -= 0.05
            note += f" RSI {rsi14:.0f} oversold."

    # Clamp
    structure_v = max(0.0, min(1.0, structure_v))

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
            "above_ema20": float(above_ema20),
            "above_ema50": float(above_ema50),
            "recent_breakout": float(breakout),
            "recent_breakdown": float(breakdown),
            "rsi14": float(rsi14) if rsi14 is not None else 0.0,
            "pct_change_5d": float(pct5) if pct5 is not None else 0.0,
            "pct_change_20d": float(pct20) if pct20 is not None else 0.0,
            "pct_change_60d": float(pct60) if pct60 is not None else 0.0,
            "n_bars": float(n),
        },
        notes=note,
    )

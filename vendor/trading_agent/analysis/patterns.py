"""
Candlestick pattern detection.
Returns boolean Series where True = pattern present on that bar.
"""

import pandas as pd
import numpy as np


def _body(o: pd.Series, c: pd.Series) -> pd.Series:
    return (c - o).abs()


def _range(h: pd.Series, l: pd.Series) -> pd.Series:
    return h - l


def _upper_shadow(o: pd.Series, h: pd.Series, c: pd.Series) -> pd.Series:
    return h - pd.concat([o, c], axis=1).max(axis=1)


def _lower_shadow(o: pd.Series, l: pd.Series, c: pd.Series) -> pd.Series:
    return pd.concat([o, c], axis=1).min(axis=1) - l


# ── Single-bar patterns ───────────────────────────────────────────────────────

def doji(df: pd.DataFrame, threshold: float = 0.05) -> pd.Series:
    """Body is less than threshold% of the full range."""
    o, c, h, l = df["open"], df["close"], df["high"], df["low"]
    rng = _range(h, l).replace(0, np.nan)
    return (_body(o, c) / rng) < threshold


def hammer(df: pd.DataFrame) -> pd.Series:
    """Small body near the top, long lower shadow (≥2× body), bullish reversal."""
    o, c, h, l = df["open"], df["close"], df["high"], df["low"]
    body = _body(o, c)
    lower = _lower_shadow(o, l, c)
    upper = _upper_shadow(o, h, c)
    rng = _range(h, l).replace(0, np.nan)
    return (lower >= 2 * body) & (upper <= body) & (body / rng < 0.35)


def shooting_star(df: pd.DataFrame) -> pd.Series:
    """Small body near the bottom, long upper shadow – bearish reversal."""
    o, c, h, l = df["open"], df["close"], df["high"], df["low"]
    body = _body(o, c)
    lower = _lower_shadow(o, l, c)
    upper = _upper_shadow(o, h, c)
    rng = _range(h, l).replace(0, np.nan)
    return (upper >= 2 * body) & (lower <= body) & (body / rng < 0.35)


def bullish_engulfing(df: pd.DataFrame) -> pd.Series:
    """Current bar engulfs the prior bar and closes higher."""
    o, c = df["open"], df["close"]
    prev_o, prev_c = o.shift(1), c.shift(1)
    return (
        (c > o)              # current is bullish
        & (prev_c < prev_o)  # prior is bearish
        & (o <= prev_c)      # current opens at or below prior close
        & (c >= prev_o)      # current closes at or above prior open
    )


def bearish_engulfing(df: pd.DataFrame) -> pd.Series:
    """Current bar engulfs the prior bar and closes lower."""
    o, c = df["open"], df["close"]
    prev_o, prev_c = o.shift(1), c.shift(1)
    return (
        (c < o)
        & (prev_c > prev_o)
        & (o >= prev_c)
        & (c <= prev_o)
    )


def morning_star(df: pd.DataFrame) -> pd.Series:
    """3-bar bullish reversal pattern."""
    o, c = df["open"], df["close"]
    body = _body(o, c)
    return (
        (c.shift(2) < o.shift(2))                   # bar -2 bearish
        & (body.shift(1) < body.shift(2) * 0.3)     # bar -1 small body
        & (c > o)                                    # bar 0 bullish
        & (c > (o.shift(2) + c.shift(2)) / 2)       # bar 0 closes above midpoint of bar -2
    )


def evening_star(df: pd.DataFrame) -> pd.Series:
    """3-bar bearish reversal pattern."""
    o, c = df["open"], df["close"]
    body = _body(o, c)
    return (
        (c.shift(2) > o.shift(2))
        & (body.shift(1) < body.shift(2) * 0.3)
        & (c < o)
        & (c < (o.shift(2) + c.shift(2)) / 2)
    )


# ── Add all pattern columns to a DataFrame ───────────────────────────────────

def add_all_patterns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["pat_doji"]              = doji(df)
    df["pat_hammer"]            = hammer(df)
    df["pat_shooting_star"]     = shooting_star(df)
    df["pat_bull_engulfing"]    = bullish_engulfing(df)
    df["pat_bear_engulfing"]    = bearish_engulfing(df)
    df["pat_morning_star"]      = morning_star(df)
    df["pat_evening_star"]      = evening_star(df)
    return df

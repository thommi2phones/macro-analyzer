"""
Technical indicator calculations.

All functions accept/return pandas Series or DataFrames.
No external TA libraries required – pure pandas + numpy.
"""

import numpy as np
import pandas as pd


# ── Trend ─────────────────────────────────────────────────────────────────────

def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()


# ── Momentum ──────────────────────────────────────────────────────────────────

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (macd_line, signal_line, histogram)."""
    fast_ema = ema(series, fast)
    slow_ema = ema(series, slow)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, signal_period)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def stochastic(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    k_period: int = 14,
    d_period: int = 3,
) -> tuple[pd.Series, pd.Series]:
    """Returns (%K, %D)."""
    lowest_low = low.rolling(k_period).min()
    highest_high = high.rolling(k_period).max()
    k = 100 * (close - lowest_low) / (highest_high - lowest_low).replace(0, np.nan)
    d = k.rolling(d_period).mean()
    return k, d


# ── Volatility ────────────────────────────────────────────────────────────────

def bollinger_bands(
    series: pd.Series,
    period: int = 20,
    std_dev: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Returns (upper, mid, lower)."""
    mid = sma(series, period)
    std = series.rolling(window=period).std()
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    return upper, mid, lower


def atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    tr = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(com=period - 1, min_periods=period).mean()


# ── Volume ────────────────────────────────────────────────────────────────────

def volume_sma(volume: pd.Series, period: int = 20) -> pd.Series:
    return volume.rolling(window=period).mean()


def volume_ratio(volume: pd.Series, period: int = 20) -> pd.Series:
    """Current volume divided by N-period average volume."""
    return volume / volume_sma(volume, period).replace(0, np.nan)


# ── Composite: add all indicators to a DataFrame ─────────────────────────────

def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds all standard indicators as columns to an OHLCV DataFrame.
    Input columns expected: open, high, low, close, volume
    """
    df = df.copy()
    c = df["close"]
    h, l, v = df["high"], df["low"], df["volume"]

    # EMAs
    for p in [9, 20, 50, 200]:
        df[f"ema_{p}"] = ema(c, p)

    # SMAs
    for p in [20, 50, 200]:
        df[f"sma_{p}"] = sma(c, p)

    # RSI
    df["rsi_14"] = rsi(c, 14)

    # MACD
    df["macd"], df["macd_signal"], df["macd_hist"] = macd(c)

    # Bollinger Bands
    df["bb_upper"], df["bb_mid"], df["bb_lower"] = bollinger_bands(c)

    # ATR
    df["atr_14"] = atr(h, l, c, 14)

    # Volume
    df["volume_sma_20"] = volume_sma(v, 20)
    df["volume_ratio"] = volume_ratio(v, 20)

    # Stochastic
    df["stoch_k"], df["stoch_d"] = stochastic(h, l, c)

    return df

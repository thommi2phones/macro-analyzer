"""Tests for prices/ package — pure functions only (no network).

Symbol mapping + technical indicators. Live yfinance fetches are NOT
tested here — keep tests deterministic and offline.
"""

from __future__ import annotations

import pytest

from macro_positioning.prices.provider import PriceBar
from macro_positioning.prices.symbol_map import (
    is_crypto,
    is_index,
    to_yfinance_symbol,
)
from macro_positioning.prices.technicals import (
    atr,
    compute_technical_features,
    ema,
    higher_highs,
    higher_lows,
    lower_highs,
    lower_lows,
    pct_change,
    pct_from,
    recent_breakdown,
    recent_breakout,
    rsi,
    sma,
)


# ---------------------------------------------------------------------------
# Symbol mapping
# ---------------------------------------------------------------------------

def test_yf_equity_passthrough():
    assert to_yfinance_symbol("URA") == "URA"
    assert to_yfinance_symbol("nvda") == "NVDA"
    assert to_yfinance_symbol("  TSM ") == "TSM"


def test_yf_crypto_appended():
    assert to_yfinance_symbol("BTC") == "BTC-USD"
    assert to_yfinance_symbol("ETH") == "ETH-USD"
    assert to_yfinance_symbol("SOL") == "SOL-USD"


def test_yf_indices_mapped():
    assert to_yfinance_symbol("VIX") == "^VIX"
    assert to_yfinance_symbol("SPX") == "^GSPC"
    assert to_yfinance_symbol("DXY") == "DX-Y.NYB"


def test_is_crypto():
    assert is_crypto("BTC") is True
    assert is_crypto("eth") is True
    assert is_crypto("URA") is False


def test_is_index():
    assert is_index("VIX") is True
    assert is_index("DXY") is True
    assert is_index("URA") is False


# ---------------------------------------------------------------------------
# SMA / pct_from
# ---------------------------------------------------------------------------

def test_sma_simple():
    assert sma([1, 2, 3, 4, 5], 3) == pytest.approx(4.0)
    assert sma([1, 2, 3], 3) == pytest.approx(2.0)


def test_sma_too_few_returns_none():
    assert sma([1, 2], 5) is None
    assert sma([], 3) is None


def test_pct_from():
    assert pct_from(110, 100) == pytest.approx(0.10)
    assert pct_from(90, 100) == pytest.approx(-0.10)
    assert pct_from(100, None) is None
    assert pct_from(100, 0) is None


# ---------------------------------------------------------------------------
# ATR
# ---------------------------------------------------------------------------

def _make_bars(closes: list[float], highs: list[float] | None = None, lows: list[float] | None = None) -> list[PriceBar]:
    if highs is None:
        highs = [c + 1 for c in closes]
    if lows is None:
        lows = [c - 1 for c in closes]
    return [
        PriceBar(
            ticker="X",
            observed_at=f"2026-01-{i+1:02d}",
            close=c,
            high=h,
            low=l,
        )
        for i, (c, h, l) in enumerate(zip(closes, highs, lows))
    ]


def test_atr_too_few_bars():
    bars = _make_bars([100, 101])
    assert atr(bars, window=14) is None


def test_atr_simple_constant_range():
    # 20 bars where every TR is exactly 2.0 (h-l=2 each bar) → ATR=2.0
    bars = _make_bars([100] * 20, highs=[101] * 20, lows=[99] * 20)
    assert atr(bars, window=14) == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------

def test_rsi_too_few_returns_none():
    assert rsi([1, 2, 3], 14) is None


def test_rsi_all_gains_returns_100():
    closes = list(range(1, 30))
    assert rsi(closes, 14) == pytest.approx(100.0)


def test_rsi_all_losses_returns_zero():
    closes = list(range(30, 1, -1))
    val = rsi(closes, 14)
    # All-loss returns 100 - 100/(1+0/avg_loss) = 100 - 100/(1+0) = 0 (avg_gain=0)
    # Technically: rs = 0/avg_loss = 0 → rsi = 100 - 100/(1+0) = 0
    assert val == pytest.approx(0.0)


def test_rsi_alternating_returns_around_50():
    # +1, -1, +1, -1 ... → balanced, RSI ≈ 50
    closes = [100]
    for i in range(1, 30):
        closes.append(closes[-1] + (1 if i % 2 == 0 else -1))
    val = rsi(closes, 14)
    assert val is not None
    assert 30 < val < 70  # roughly balanced


# ---------------------------------------------------------------------------
# Structure detection
# ---------------------------------------------------------------------------

def test_higher_highs_and_lows_uptrend():
    # Steadily increasing
    highs = list(range(1, 21))
    lows = list(range(0, 20))
    assert higher_highs(highs) is True
    assert higher_lows(lows) is True
    assert lower_highs(highs) is False
    assert lower_lows(lows) is False


def test_lower_highs_and_lows_downtrend():
    highs = list(range(20, 0, -1))
    lows = list(range(19, -1, -1))
    assert lower_highs(highs) is True
    assert lower_lows(lows) is True
    assert higher_highs(highs) is False
    assert higher_lows(lows) is False


# ---------------------------------------------------------------------------
# Breakout / breakdown
# ---------------------------------------------------------------------------

def test_recent_breakout_when_last_above_prior_max():
    highs = [100] * 20 + [105]
    assert recent_breakout(highs, lookback=20) is True


def test_recent_breakout_false_when_last_below_prior_max():
    highs = [100] * 20 + [99]
    assert recent_breakout(highs, lookback=20) is False


def test_recent_breakdown():
    lows = [100] * 20 + [95]
    assert recent_breakdown(lows, lookback=20) is True


# ---------------------------------------------------------------------------
# compute_technical_features end-to-end
# ---------------------------------------------------------------------------

def test_compute_features_uptrend():
    """50+ bars trending up should yield bullish features."""
    closes = [100 + i for i in range(60)]  # steady uptrend
    bars = _make_bars(closes)
    feats = compute_technical_features(bars)
    assert feats["n_bars"] == 60
    assert feats["close"] == 159
    assert feats["above_ma50"] is True
    assert feats["higher_highs"] is True
    assert feats["higher_lows"] is True
    assert feats["lower_highs"] is False
    assert feats["lower_lows"] is False


def test_compute_features_short_history():
    """Only 5 bars: most features should be None or False."""
    bars = _make_bars([100, 101, 102, 103, 104])
    feats = compute_technical_features(bars)
    assert feats["n_bars"] == 5
    assert feats["close"] == 104
    assert feats["ma20"] is None
    assert feats["ma50"] is None
    assert feats["ma200"] is None
    assert feats["above_ma50"] is False  # ma50 is None → False


def test_compute_features_empty():
    feats = compute_technical_features([])
    assert feats == {"n_bars": 0}


# ---------------------------------------------------------------------------
# EMA
# ---------------------------------------------------------------------------

def test_ema_too_few_returns_none():
    assert ema([1, 2, 3], 5) is None


def test_ema_constant_series_equals_constant():
    """EMA of a constant series == the constant."""
    closes = [100.0] * 50
    assert ema(closes, 20) == pytest.approx(100.0)


def test_ema_accelerating_uptrend_above_sma():
    """EMA reacts faster to recent moves than SMA. On a *linear* uptrend
    EMA == SMA (math identity), but on an accelerating series (curve up)
    EMA should be clearly higher because recent bars get more weight."""
    # Accelerating: y = i^1.5 — recent bars climb faster
    closes = [float(i) ** 1.5 for i in range(1, 41)]
    sma_v = sma(closes, 20)
    ema_v = ema(closes, 20)
    assert ema_v is not None and sma_v is not None
    assert ema_v > sma_v


# ---------------------------------------------------------------------------
# pct_change
# ---------------------------------------------------------------------------

def test_pct_change_basic():
    closes = [100, 105, 110]
    assert pct_change(closes, 1) == pytest.approx(110 / 105 - 1)
    assert pct_change(closes, 2) == pytest.approx(0.10)


def test_pct_change_too_few_returns_none():
    assert pct_change([100, 101], 5) is None


def test_pct_change_zero_lookback_returns_none():
    assert pct_change([100, 105], 0) is None


def test_pct_change_handles_zero_base():
    closes = [0.0, 5.0]
    # base near zero → 0.0 (avoids inf)
    assert pct_change(closes, 1) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Multi-horizon momentum in compute_technical_features
# ---------------------------------------------------------------------------

def test_compute_features_includes_momentum_horizons():
    bars = _make_bars([100 + i for i in range(70)])
    feats = compute_technical_features(bars)
    assert feats["pct_change_1d"] is not None
    assert feats["pct_change_5d"] is not None
    assert feats["pct_change_20d"] is not None
    assert feats["pct_change_60d"] is not None
    # Steady linear uptrend → all positive
    assert feats["pct_change_5d"] > 0
    assert feats["pct_change_20d"] > 0
    assert feats["pct_change_60d"] > 0


def test_compute_features_includes_ema():
    bars = _make_bars([100 + i for i in range(60)])
    feats = compute_technical_features(bars)
    assert feats["ema20"] is not None
    assert feats["ema50"] is not None
    assert feats["above_ema20"] is True
    assert feats["above_ema50"] is True


def test_compute_features_downtrend_momentum_negative():
    bars = _make_bars([200 - i for i in range(70)])
    feats = compute_technical_features(bars)
    assert feats["pct_change_5d"] < 0
    assert feats["pct_change_20d"] < 0
    assert feats["pct_change_60d"] < 0
    assert feats["above_ema50"] is False

"""Technical indicators — pure functions over a PriceBar list.

NO numpy/pandas dependency on purpose: keeps this module fast to import,
trivial to test, and easy to reason about. We have N≤200 bars per ticker;
manual loops are fine.

Indicators:
  - Simple moving average (SMA) for any window
  - Average true range (ATR) over 14 bars
  - Relative strength index (RSI) over 14 bars
  - % distance from MA
  - Higher highs / higher lows over a window
  - Above/below MA
  - Recent breakout / failed breakout flags

Output is a flat dict of float/bool features the technical_scorer
heuristic consumes (per framework §5).
"""

from __future__ import annotations

from typing import Iterable

from macro_positioning.prices.provider import PriceBar


# ---------------------------------------------------------------------------
# Moving averages
# ---------------------------------------------------------------------------

def sma(closes: list[float], window: int) -> float | None:
    """Simple moving average of last `window` closes. None if too few bars."""
    if len(closes) < window or window <= 0:
        return None
    return sum(closes[-window:]) / window


def pct_from(price: float, reference: float | None) -> float | None:
    """(price - reference) / reference. None when reference missing/zero."""
    if reference is None or reference == 0:
        return None
    return (price - reference) / reference


# ---------------------------------------------------------------------------
# ATR — average true range
# ---------------------------------------------------------------------------

def atr(bars: list[PriceBar], window: int = 14) -> float | None:
    """ATR over last `window` true-range values. Wilder's method."""
    if len(bars) < window + 1:
        return None
    trs: list[float] = []
    for i in range(1, len(bars)):
        prev_close = bars[i - 1].close
        h = bars[i].high if bars[i].high is not None else bars[i].close
        l = bars[i].low if bars[i].low is not None else bars[i].close
        tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        trs.append(tr)
    if len(trs) < window:
        return None
    return sum(trs[-window:]) / window


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------

def rsi(closes: list[float], window: int = 14) -> float | None:
    """Relative strength index. Wilder smoothing approximation via SMA."""
    if len(closes) < window + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0) for d in deltas[-window:]]
    losses = [max(-d, 0) for d in deltas[-window:]]
    avg_gain = sum(gains) / window
    avg_loss = sum(losses) / window
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


# ---------------------------------------------------------------------------
# Structure detection — higher highs / higher lows
# ---------------------------------------------------------------------------

def higher_highs(highs: list[float], window: int = 20) -> bool:
    if len(highs) < window:
        return False
    recent_max = max(highs[-window // 2:])
    earlier_max = max(highs[-window:-window // 2])
    return recent_max > earlier_max


def higher_lows(lows: list[float], window: int = 20) -> bool:
    if len(lows) < window:
        return False
    recent_min = min(lows[-window // 2:])
    earlier_min = min(lows[-window:-window // 2])
    return recent_min > earlier_min


def lower_highs(highs: list[float], window: int = 20) -> bool:
    if len(highs) < window:
        return False
    recent_max = max(highs[-window // 2:])
    earlier_max = max(highs[-window:-window // 2])
    return recent_max < earlier_max


def lower_lows(lows: list[float], window: int = 20) -> bool:
    if len(lows) < window:
        return False
    recent_min = min(lows[-window // 2:])
    earlier_min = min(lows[-window:-window // 2])
    return recent_min < earlier_min


# ---------------------------------------------------------------------------
# Recent breakout heuristic
# ---------------------------------------------------------------------------

def recent_breakout(highs: list[float], lookback: int = 20) -> bool:
    """True when the last close pierces the prior `lookback` highs."""
    if len(highs) < lookback + 1:
        return False
    last = highs[-1]
    prior_max = max(highs[-(lookback + 1):-1])
    return last > prior_max


def recent_breakdown(lows: list[float], lookback: int = 20) -> bool:
    if len(lows) < lookback + 1:
        return False
    last = lows[-1]
    prior_min = min(lows[-(lookback + 1):-1])
    return last < prior_min


# ---------------------------------------------------------------------------
# Top-level: build a feature dict from a PriceBar list
# ---------------------------------------------------------------------------

def compute_technical_features(bars: list[PriceBar]) -> dict:
    """Return a flat features dict the technical_scorer consumes.

    Keys:
      close, ma20, ma50, ma200, pct_from_ma20, pct_from_ma50, pct_from_ma200,
      atr14, rsi14, higher_highs, higher_lows, lower_highs, lower_lows,
      above_ma50, above_ma200, recent_breakout, recent_breakdown,
      n_bars
    """
    if not bars:
        return {"n_bars": 0}

    closes = [b.close for b in bars]
    highs = [b.high if b.high is not None else b.close for b in bars]
    lows = [b.low if b.low is not None else b.close for b in bars]
    last = closes[-1]

    ma20_v = sma(closes, 20)
    ma50_v = sma(closes, 50)
    ma200_v = sma(closes, 200)

    return {
        "n_bars": len(bars),
        "close": last,
        "ma20": ma20_v,
        "ma50": ma50_v,
        "ma200": ma200_v,
        "pct_from_ma20": pct_from(last, ma20_v),
        "pct_from_ma50": pct_from(last, ma50_v),
        "pct_from_ma200": pct_from(last, ma200_v),
        "atr14": atr(bars, 14),
        "rsi14": rsi(closes, 14),
        "higher_highs": higher_highs(highs, 20),
        "higher_lows": higher_lows(lows, 20),
        "lower_highs": lower_highs(highs, 20),
        "lower_lows": lower_lows(lows, 20),
        "above_ma50": (ma50_v is not None and last > ma50_v),
        "above_ma200": (ma200_v is not None and last > ma200_v),
        "recent_breakout": recent_breakout(highs, 20),
        "recent_breakdown": recent_breakdown(lows, 20),
    }

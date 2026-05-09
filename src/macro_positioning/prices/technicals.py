"""Technical indicators — pure functions over a PriceBar list.

NO numpy/pandas dependency on purpose: keeps this module fast to import,
trivial to test, and easy to reason about. We have N≤200 bars per ticker;
manual loops are fine.

Indicators:
  - Simple moving average (SMA)
  - Exponential moving average (EMA) — recency-weighted, the preferred
    trend-following indicator for active traders
  - Average true range (ATR) over 14 bars
  - Relative strength index (RSI) over 14 bars
  - Multi-horizon price momentum: 1d / 3d / 5d / 20d / 60d % change
    (approximates daily / 3-day / weekly / monthly / cycle trend)
  - % distance from MA
  - Higher highs / higher lows over a window
  - Above/below SMA + EMA
  - Recent breakout / failed breakout flags

INTRADAY note: this module operates on whatever bars it's given. With
daily bars (current default), windows are in trading days. Intraday
support (4h/12h) needs the price fetcher to get intraday data first —
the math here is timeframe-agnostic. See `prices/provider.py` TODO.

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


def ema(closes: list[float], window: int) -> float | None:
    """Exponential moving average over `window`. None if too few bars.

    Recency-weighted: the most recent close gets weight α = 2/(window+1).
    EMA reacts faster to price changes than SMA — preferred for trend
    following per the trading framework's §5 momentum guidance.
    """
    if len(closes) < window or window <= 0:
        return None
    alpha = 2.0 / (window + 1)
    # Seed with SMA of the first `window` closes (Wilder/standard convention)
    seed = sum(closes[:window]) / window
    val = seed
    for c in closes[window:]:
        val = alpha * c + (1 - alpha) * val
    return val


def pct_change(closes: list[float], lookback: int) -> float | None:
    """% change of the most recent close vs `lookback` bars ago.

    Returns 0.0 for very small bases (avoids spurious infinities).
    None when too few bars.
    """
    if len(closes) <= lookback or lookback <= 0:
        return None
    base = closes[-(lookback + 1)]
    if abs(base) < 1e-9:
        return 0.0
    return (closes[-1] - base) / base


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

def compute_volume_features(bars: list[PriceBar]) -> dict:
    """Return a flat volume features dict the volume_flow_confirmation
    scorer consumes. Volume bars with None are skipped (some sources
    don't report volume for FX/indices).
    """
    vols = [b.volume for b in bars if b.volume is not None]
    if not vols:
        return {"n_volume_bars": 0}
    closes = [b.close for b in bars]
    last_5 = vols[-5:] if len(vols) >= 5 else vols
    last_20 = vols[-20:] if len(vols) >= 20 else vols
    vol_5d_avg = sum(last_5) / len(last_5)
    vol_20d_avg = sum(last_20) / len(last_20)
    pct5 = pct_change(closes, 5) if len(closes) >= 6 else None
    return {
        "n_volume_bars": len(vols),
        "vol_5d_avg": vol_5d_avg,
        "vol_20d_avg": vol_20d_avg,
        "pct_change_5d": pct5,
    }


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
    ema20_v = ema(closes, 20)
    ema50_v = ema(closes, 50)
    ema200_v = ema(closes, 200)

    return {
        "n_bars": len(bars),
        "close": last,
        # SMAs (lagging, smoother)
        "ma20": ma20_v,
        "ma50": ma50_v,
        "ma200": ma200_v,
        "pct_from_ma20": pct_from(last, ma20_v),
        "pct_from_ma50": pct_from(last, ma50_v),
        "pct_from_ma200": pct_from(last, ma200_v),
        # EMAs (recency-weighted, faster trend signal)
        "ema20": ema20_v,
        "ema50": ema50_v,
        "ema200": ema200_v,
        "pct_from_ema20": pct_from(last, ema20_v),
        "pct_from_ema50": pct_from(last, ema50_v),
        "pct_from_ema200": pct_from(last, ema200_v),
        # Volatility / momentum primitives
        "atr14": atr(bars, 14),
        "rsi14": rsi(closes, 14),
        # Multi-horizon momentum (approximates daily / 3-day / weekly /
        # monthly / cycle trend strength on daily bars)
        "pct_change_1d": pct_change(closes, 1),
        "pct_change_3d": pct_change(closes, 3),
        "pct_change_5d": pct_change(closes, 5),    # ≈ weekly
        "pct_change_20d": pct_change(closes, 20),  # ≈ monthly
        "pct_change_60d": pct_change(closes, 60),  # ≈ quarterly / cycle
        # Structure
        "higher_highs": higher_highs(highs, 20),
        "higher_lows": higher_lows(lows, 20),
        "lower_highs": lower_highs(highs, 20),
        "lower_lows": lower_lows(lows, 20),
        "above_ma50": (ma50_v is not None and last > ma50_v),
        "above_ma200": (ma200_v is not None and last > ma200_v),
        "above_ema20": (ema20_v is not None and last > ema20_v),
        "above_ema50": (ema50_v is not None and last > ema50_v),
        "recent_breakout": recent_breakout(highs, 20),
        "recent_breakdown": recent_breakdown(lows, 20),
    }

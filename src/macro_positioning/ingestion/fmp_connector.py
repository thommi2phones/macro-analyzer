"""FMP (Financial Modeling Prep) historical price connector.

Free tier: 250 calls/day.
API docs: https://site.financialmodelingprep.com/developer/docs

Used for: OHLCV price data to add technical overlay context to the brain.
Not newsletter content — feeds into MarketObservation, not RawDocument.

TODO(stream-a): implement as stub below.
"""

from __future__ import annotations

import logging

from macro_positioning.core.models import MarketObservation

logger = logging.getLogger(__name__)

FMP_BASE = "https://financialmodelingprep.com/api/v3"


def fetch_historical_prices(
    symbol: str,
    days: int = 90,
    api_key: str | None = None,
) -> list[dict]:
    """Get historical daily OHLCV for a symbol.

    TODO(stream-a):
      - GET {FMP_BASE}/historical-price-full/{symbol}?timeseries={days}
      - Returns list of {date, open, high, low, close, volume, vwap, change_pct}
    """
    raise NotImplementedError("Stream A: implement FMP historical prices")


def fetch_technical_indicator(
    symbol: str,
    indicator: str = "rsi",
    period: int = 14,
    api_key: str | None = None,
) -> list[dict]:
    """Get technical indicator values for a symbol.

    Supported: rsi, sma, ema, wma, dema, tema, williams, adx, standardDeviation

    TODO(stream-a):
      - GET {FMP_BASE}/technical_indicator/daily/{symbol}?period={period}&type={indicator}
    """
    raise NotImplementedError("Stream A: implement FMP technical indicators")


def to_market_observation(
    symbol: str,
    metric: str,
    value: str | float,
) -> MarketObservation:
    """Helper: wrap an FMP data point as a MarketObservation for the brain."""
    import hashlib
    obs_id = hashlib.sha1(f"fmp|{symbol}|{metric}|{value}".encode()).hexdigest()[:12]
    return MarketObservation(
        observation_id=obs_id,
        market=symbol,
        metric=metric,
        value=str(value),
        source="fmp",
    )

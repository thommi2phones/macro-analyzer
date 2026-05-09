"""Price provider abstraction + yfinance default implementation.

Provider interface lets us swap to FMP/Finnhub/Polygon later without
touching scoring/runner.py. yfinance default is free, no API key, and
covers equities/ETFs/indices/crypto via symbol mapping.

Tradeoffs:
- yfinance scrapes Yahoo Finance — fragile, can break unannounced
- Free, no rate limit headaches
- Daily history is solid; intraday is best-effort

For Phase 7 prod use FMP/Finnhub with paid tier; yfinance gets us
running today with zero infrastructure cost.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from typing import Iterable

from pydantic import BaseModel

from macro_positioning.prices.symbol_map import to_yfinance_symbol


logger = logging.getLogger(__name__)


class PriceBar(BaseModel):
    """One OHLCV bar."""
    ticker: str
    observed_at: str       # ISO date (YYYY-MM-DD) for daily, ISO datetime for intraday
    timeframe: str = "1D"
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float
    volume: int | None = None
    provider: str = "unknown"


class PriceProvider(ABC):
    """Abstract provider. Implementations fetch + normalize to PriceBar."""

    name: str = "abstract"

    @abstractmethod
    def fetch_history(
        self,
        ticker: str,
        *,
        days: int = 200,
        timeframe: str = "1D",
    ) -> list[PriceBar]:
        """Return up to `days` bars ending at the most recent close."""
        raise NotImplementedError

    def fetch_many(
        self,
        tickers: Iterable[str],
        *,
        days: int = 200,
        timeframe: str = "1D",
    ) -> dict[str, list[PriceBar]]:
        """Default: per-ticker iteration. Providers that support batch
        endpoints can override for efficiency."""
        out: dict[str, list[PriceBar]] = {}
        for t in tickers:
            try:
                out[t] = self.fetch_history(t, days=days, timeframe=timeframe)
            except Exception as exc:
                logger.warning("price fetch failed for %s: %s", t, exc)
                out[t] = []
        return out


# ---------------------------------------------------------------------------
# yfinance implementation
# ---------------------------------------------------------------------------

class YFinanceProvider(PriceProvider):
    """yfinance-backed provider. Free, no key, covers most tickers."""

    name = "yfinance"

    def fetch_history(
        self,
        ticker: str,
        *,
        days: int = 200,
        timeframe: str = "1D",
    ) -> list[PriceBar]:
        # Lazy import — yfinance is optional in the abstract sense; if it's
        # not installed, callers can still use a different provider.
        import yfinance as yf

        symbol = to_yfinance_symbol(ticker)
        if timeframe != "1D":
            # Phase 7: support intraday. For now stick to daily.
            raise NotImplementedError(f"timeframe {timeframe!r} not supported yet")

        # yfinance Ticker.history() with a period kwarg uses heuristic
        # ranges. For predictable behavior, compute explicit start/end.
        end = datetime.now()
        start = end - timedelta(days=days * 2)  # buffer for non-trading days

        try:
            hist = yf.Ticker(symbol).history(
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                interval="1d",
                auto_adjust=False,
                actions=False,
            )
        except Exception as exc:
            logger.warning("yfinance history(%s) failed: %s", symbol, exc)
            return []

        if hist is None or hist.empty:
            return []

        bars: list[PriceBar] = []
        for ts, row in hist.iterrows():
            try:
                close = float(row["Close"])
            except (KeyError, ValueError, TypeError):
                continue
            if not close or close != close:  # NaN check
                continue
            bars.append(
                PriceBar(
                    ticker=ticker.upper(),
                    observed_at=ts.strftime("%Y-%m-%d"),
                    timeframe="1D",
                    open=_to_float(row.get("Open")),
                    high=_to_float(row.get("High")),
                    low=_to_float(row.get("Low")),
                    close=close,
                    volume=_to_int(row.get("Volume")),
                    provider="yfinance",
                )
            )

        # Trim to most recent `days` records (pandas may have returned more)
        return bars[-days:]


def _to_float(v) -> float | None:
    try:
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


def _to_int(v) -> int | None:
    try:
        f = float(v)
        if f != f:
            return None
        return int(f)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Default provider factory
# ---------------------------------------------------------------------------

def default_provider() -> PriceProvider:
    """Get the default price provider. Set via env later if needed."""
    return YFinanceProvider()

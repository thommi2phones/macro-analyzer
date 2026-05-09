"""Symbol mapping — translate our internal tickers to provider-specific symbols.

Our watchlist uses bare tickers (URA, BTC, DXY). Different price providers
need different symbol formats:
  - yfinance:   crypto needs BTC-USD; indices need ^DXY / ^VIX
  - FMP:        equities use bare; crypto uses BTCUSD
  - Finnhub:    equities use bare; crypto uses BINANCE:BTCUSDT

Keep this isolated so swapping providers doesn't ripple into runner/scoring.
"""

from __future__ import annotations


# Crypto tickers — these need provider-specific suffixes
_CRYPTO_TICKERS = {"BTC", "ETH", "SOL", "DOGE", "ADA", "DOT", "MATIC", "AVAX", "LINK", "LTC", "XRP", "BNB"}

# Index / FX tickers — these need ^ prefix on yfinance
_YF_INDICES = {
    "DXY": "DX-Y.NYB",   # Dollar index — Yahoo's specific symbol
    "VIX": "^VIX",
    "SPX": "^GSPC",
    "NDX": "^NDX",
    "RUT": "^RUT",
}

# Some tickers we use that need explicit yfinance overrides (data quality / availability)
_YF_OVERRIDES = {
    # Add as needed when yfinance's default doesn't match what we expect
}


def to_yfinance_symbol(ticker: str) -> str:
    """Convert our ticker to yfinance's symbol format.

    Examples:
      URA  -> URA
      BTC  -> BTC-USD
      DXY  -> DX-Y.NYB
      VIX  -> ^VIX
    """
    t = ticker.upper().strip()
    if t in _YF_OVERRIDES:
        return _YF_OVERRIDES[t]
    if t in _YF_INDICES:
        return _YF_INDICES[t]
    if t in _CRYPTO_TICKERS:
        return f"{t}-USD"
    return t


def is_crypto(ticker: str) -> bool:
    return ticker.upper().strip() in _CRYPTO_TICKERS


def is_index(ticker: str) -> bool:
    return ticker.upper().strip() in _YF_INDICES

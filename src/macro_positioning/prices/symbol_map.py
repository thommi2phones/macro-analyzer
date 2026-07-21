"""Symbol mapping — translate our internal tickers to provider-specific symbols.

Our watchlist uses bare tickers (URA, BTC, DXY). Different price providers
need different symbol formats:
  - yfinance:   crypto needs BTC-USD; indices need ^DXY / ^VIX
  - FMP:        equities use bare; crypto uses BTCUSD
  - Finnhub:    equities use bare; crypto uses BINANCE:BTCUSDT

Keep this isolated so swapping providers doesn't ripple into runner/scoring.
"""

from __future__ import annotations

import re


# A plausible US equity/ETF symbol: 1–5 uppercase letters, optional .CLASS
# (BRK.B). Excludes spaces, digits, ':', and over-long verbose labels.
_PLAUSIBLE_EQUITY = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")


# Crypto tickers — these need provider-specific suffixes
_CRYPTO_TICKERS = {"BTC", "ETH", "SOL", "DOGE", "ADA", "DOT", "MATIC", "AVAX", "LINK", "LTC", "XRP", "BNB"}

# ── Accuracy-layer tracked crypto universe ──────────────────────────────────
# The ONLY crypto we score for source accuracy: the coins tradeable on
# Coinbase US (user-supplied watchlist). Any crypto call outside this set is
# `unpriceable` and excluded — no point scoring an untradeable coin. Equities,
# by contrast, are NOT a fixed list: they're scored dynamically from whatever
# the channels call (see resolve_symbol). All map to yfinance `-USD`.
_TRACKED_CRYPTO = {
    "BTC", "ETH", "SOL", "XRP", "DOGE", "AVAX", "LINK", "LTC",
    "AAVE", "FET", "HBAR", "ONDO", "SUI", "TAO", "TRX", "HYPE",
}

# Quote/pair suffixes that mark a raw ticker as a crypto pair rather than a
# bare equity symbol. Order matters — strip the longest first.
_CRYPTO_QUOTE_SUFFIXES = ("USDT", "USDC", "BUSD", "TUSD", "PERP", "USD")

# Commodity/FX aliases mapped to a yfinance-priceable symbol. Calls say
# "GOLD"/"XAU"; price them off the continuous futures contract.
_EQUITY_ALIASES = {
    "GOLD": "GC=F", "XAU": "GC=F", "XAUUSD": "GC=F",
    "SILVER": "SI=F", "XAG": "SI=F", "XAGUSD": "SI=F",
}

# Newer coins where yfinance disambiguates the symbol with a CoinMarketCap
# id suffix (the plain `{COIN}-USD` returns no history). Verified against
# the user's watchlist closes (HYPE 64.6, SUI 0.77, TAO 209).
_CRYPTO_YF_OVERRIDES = {
    "HYPE": "HYPE32196-USD",
    "SUI": "SUI20947-USD",
    "TAO": "TAO22974-USD",
}


def _crypto_base(raw: str) -> tuple[str | None, bool]:
    """Parse a raw call ticker into (base, is_crypto_pair).

    Returns (base_coin, True) when the raw ticker is a crypto pair
    (FARTCOIN/USDT, BTCUSD, AVAXUSDT.P → FARTCOIN/BTC/AVAX), or
    (base, False) when it's a bare symbol that should be treated as an
    equity candidate (AAPL, COIN, GOLD, BRK-B).
    """
    t = (raw or "").upper().strip()
    if not t:
        return None, False
    t = t.removesuffix(".P")  # AVAXUSDT.P → AVAXUSDT (perp marker)

    # Explicit '/' is the crypto-pair convention (FARTCOIN/USDT, SOL/USDT).
    if "/" in t:
        return (t.split("/")[0] or None), True

    # '-' / '_' separators: crypto only when the tail is a known quote
    # (BTC-USD) — otherwise it's a hyphenated equity (BRK-B) left bare.
    for sep in ("-", "_"):
        if sep in t:
            head, _, tail = t.partition(sep)
            if tail in _CRYPTO_QUOTE_SUFFIXES:
                return (head or None), True
            return (t, False)

    # No separator: a trailing quote suffix marks a pair (BTCUSD, FETUSD).
    # 'TUSD' can shadow 'FET'+'USD', so collect every candidate and PREFER
    # one that's a tracked coin; fall back to the longest-suffix strip.
    candidates = [
        t[: -len(suf)] for suf in _CRYPTO_QUOTE_SUFFIXES
        if t.endswith(suf) and len(t) > len(suf) + 1
    ]
    for c in candidates:
        if c in _TRACKED_CRYPTO:
            return c, True
    if candidates:
        return min(candidates, key=len), True  # most aggressive strip
    return t, False


def resolve_symbol(raw_ticker: str) -> str | None:
    """Map a raw call ticker to the in-scope BARE key for accuracy scoring.

    This returns the key the `prices` table is stored under (bare ticker for
    crypto, the symbol/alias for equities) — NOT the yfinance fetch symbol.
    Use `to_yfinance_symbol(key)` to get the fetch symbol. Keeping the two
    separate lets storage + lookup agree on one key while fetch translates.

    • Crypto pair → its bare coin ONLY if in the Coinbase-US tracked set
      (BTCUSD→'BTC', HYPEUSDT→'HYPE'); otherwise None (untradeable).
    • Bare symbol → equity candidate, with commodity aliases applied
      (GOLD→'GC=F'); returned as the key for a dynamic yfinance lookup.

    Returns None = `unpriceable`.
    """
    base, is_pair = _crypto_base(raw_ticker)
    if not base:
        return None
    if is_pair:
        return base if base in _TRACKED_CRYPTO else None
    # Bare symbol — commodity alias, else treat as a dynamic equity ticker.
    alias = _EQUITY_ALIASES.get(base)
    if alias:
        return alias
    # Sanity-gate equity candidates so junk extractions (macro labels,
    # crypto-cap indices, verbose "UNKNOWN — likely..." strings, TOTAL2,
    # BTC.D) don't get fetched. A real US equity/ETF symbol is 1–5 letters,
    # optionally with one dot-class (BRK.B). Anything with spaces, digits,
    # ':', or >6 chars is rejected as unpriceable.
    if _PLAUSIBLE_EQUITY.match(base):
        return base
    return None

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
    """Convert our (bare) ticker to yfinance's symbol format.

    Examples:
      URA  -> URA
      BTC  -> BTC-USD
      HYPE -> HYPE32196-USD   (CMC-id disambiguated)
      DXY  -> DX-Y.NYB
      VIX  -> ^VIX
    """
    t = ticker.upper().strip()
    if t in _YF_OVERRIDES:
        return _YF_OVERRIDES[t]
    if t in _CRYPTO_YF_OVERRIDES:
        return _CRYPTO_YF_OVERRIDES[t]
    if t in _YF_INDICES:
        return _YF_INDICES[t]
    if t in _TRACKED_CRYPTO or t in _CRYPTO_TICKERS:
        return f"{t}-USD"
    return t


def is_crypto(ticker: str) -> bool:
    return ticker.upper().strip() in _CRYPTO_TICKERS


def is_index(ticker: str) -> bool:
    return ticker.upper().strip() in _YF_INDICES

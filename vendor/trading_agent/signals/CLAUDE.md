# M2 — Signals Module CLAUDE.md

## Purpose
Generate trade signals by scanning the watchlist for setups matching
the owner's rules. Rules are YAML-defined; engine is Python.

## Files
```
signals/
├── CLAUDE.md          ← you are here
└── generator.py       ← SignalGenerator class
config/
├── rules.yaml         ← scan rules (RSI, MACD, EMA, Bollinger, breakout)
└── settings.yaml      ← watchlists, scan profiles, execution mode
```

## Signal output format
Every signal emitted must match this structure:
```python
@dataclass
class Signal:
    ticker: str
    direction: str          # "long" | "short"
    confidence: float       # 0.0–1.0 (boosted by pattern learner)
    setup_type: str         # matches owner's known setups
    entry_price: float
    stop_loss: float | None
    tp_price: float | None
    timeframe: str
    rules_triggered: list[str]
    timestamp: str          # ISO
```

## Owner's patterns (bias these rules toward these setups)
Based on trade history analysis — owner trades these primarily:
- **Breakouts** from consolidation/resistance
- **Falling wedge** (bullish reversal)
- **Symmetrical triangle** (breakout direction)
- **Cup and handle** (continuation)
- **Descending channel** (short setups)
- **Fibonacci retracement** pullbacks (0.618 confluence especially)

## Owner's preferred timeframes
- Swing: 4h, 1D, 1W (primary)
- Intraday: 1h, 15m (secondary)

## Watchlist (from settings.yaml)
Currently 10 tickers — crypto-heavy:
BTC, XRP, SOL, DOGE, HBAR, SUI + XAUUSD, XAGUSD + TSLA

## Scan profiles (from settings.yaml)
- `macro`  — weekly/daily timeframes, trend following
- `swing`  — 4h/daily, breakout + Fibonacci setups
- `intra`  — 1h/15m, momentum entries

## Rules format (rules.yaml)
```yaml
rules:
  - name: rsi_oversold
    indicator: RSI
    period: 14
    condition: "< 35"
    timeframes: ["4h", "1d"]
    weight: 0.4

  - name: ema_cross_bullish
    indicator: EMA_CROSS
    fast: 9
    slow: 21
    condition: "cross_above"
    weight: 0.6
```

## TODO for this module
- [ ] Add Fibonacci retracement detection (0.382, 0.5, 0.618, 0.786 levels)
- [ ] Add pattern confidence booster from M3 PatternLearner output
- [ ] Add breakout detection (price closes above N-period high with volume)
- [ ] Add falling wedge / symmetrical triangle pattern rules
- [ ] Multi-timeframe majority vote (signal must appear on 2/3 timeframes)
- [ ] Wire stop_loss and tp_price calculation into Signal output

## Consumes
- `data/` providers — gets OHLCV bars for indicators
- `data/trade_history_insights.json` — pattern confidence adjustments

## Consumed by
- `agent/loop.py` — filters signals, routes to execution
- `backtesting/engine.py` — replays rules on historical data

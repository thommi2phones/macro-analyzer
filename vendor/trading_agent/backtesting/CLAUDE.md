# M5 — Backtesting Module CLAUDE.md

## Purpose
Validate signal rules against historical data before going live.
Measure win rate, expectancy, drawdown, and Sharpe ratio.

## Files
```
backtesting/
├── CLAUDE.md       ← you are here
└── engine.py       ← backtester (supports vectorbt)
```

## Running
```bash
python3 main.py backtest --ticker AAPL --timeframe 1d
python3 main.py backtest --ticker BTC/USD --timeframe 4h --days 365
```

## Data source for backtests
Uses the same `data/providers/alpaca_provider.py` as live trading.
Falls back to yfinance if Alpaca data is unavailable.

## Owner's setups to backtest (priority order)
Based on trade history — test these specific setups:
1. **Fibonacci 0.618 retracement pullback** on 4h/1D — does price bounce?
2. **Falling wedge breakout** on 1D — win rate and avg R:R
3. **Symmetrical triangle breakout** — win rate by direction
4. **Breakout from N-period high** with volume confirmation
5. **Descending channel short** — when does price reject channel top?

## Metrics to report
```
Win rate           %
Avg winner         R multiple
Avg loser          R multiple
Expectancy         (winRate × avgWin) - (lossRate × avgLoss)
Max drawdown       %
Sharpe ratio
Total trades       count
Avg hold time      bars
```

## Interface expected
```python
class BacktestEngine:
    def run(ticker, rules, timeframe, start, end) -> BacktestResult: ...
    def report(result: BacktestResult) -> None: ...   # prints to stdout
```

## Integration with M3 pattern learner
- After image analysis, `data/trade_history_insights.json` lists dominant setups
- Backtest should validate those setups first
- Feed results back into signal confidence weights in rules.yaml

## TODO for this module
- [ ] Wire to M2 signal rules (currently not connected)
- [ ] Add walk-forward testing (avoid overfitting)
- [ ] Add per-setup breakdown (separate stats for each setup_type)
- [ ] Add trade log output to data/ for post-analysis
- [ ] Integrate vectorbt if not already wired

## Consumed by
- None (standalone validation tool)
- Results inform: signals/rules.yaml weight tuning

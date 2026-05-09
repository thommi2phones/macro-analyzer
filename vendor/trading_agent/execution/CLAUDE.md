# M4 — Execution Module CLAUDE.md

## Purpose
Route signals to paper or live orders via Alpaca. Handle position sizing,
risk management, and order lifecycle.

## Files
```
execution/
├── CLAUDE.md           ← you are here
├── alpaca_broker.py    ← live Alpaca order routing
└── paper_trading.py    ← paper trading simulator
```

## Alpaca accounts
```
Paper:  PA30PCRE0P06 — $100k cash, $200k buying power (2x margin)
        URL: https://paper-api.alpaca.markets
        Keys: ALPACA_API_KEY / ALPACA_SECRET_KEY in .env

Live:   Separate keys in .env: ALPACA_LIVE_API_KEY / ALPACA_LIVE_SECRET_KEY
        URL: https://api.alpaca.markets
        INACTIVE — swap into main keys + set execution.mode: live in settings.yaml
```

## Execution mode (settings.yaml)
```yaml
execution:
  mode: paper    # paper | live
```

## Risk rules (to be implemented)
The owner's trading style informs these constraints:
- **Max risk per trade**: 1–2% of account equity
- **Position sizing**: based on entry → stop loss distance
  - `qty = (account_equity * risk_pct) / (entry - stop_loss)`
- **Max open positions**: 5 concurrent
- **No averaging down** — one entry per signal
- **Crypto**: GTC orders (market never closes)
- **Equities**: DAY orders during market hours

## Order types by asset
```
Crypto  → market or limit, GTC time-in-force
Stocks  → market or limit, DAY time-in-force
Options → market or limit, DAY only (no extended hours)
```

## Interface expected by agent/loop.py
```python
class Broker:
    def place_order(signal: Signal) -> OrderResult: ...
    def get_positions() -> list[Position]: ...
    def get_account() -> AccountInfo: ...
    def cancel_order(order_id: str) -> bool: ...
    def close_position(ticker: str) -> bool: ...
```

## TODO for this module
- [ ] Implement position sizing (risk % of equity / entry-stop distance)
- [ ] Add max position count guard (reject signals if ≥ 5 open)
- [ ] Add duplicate position guard (don't re-enter if already long/short ticker)
- [ ] Add P&L tracker that writes to data/live/ after each close
- [ ] Add trailing stop support for breakout trades
- [ ] Reconcile paper_trading.py state with Alpaca paper account state

## Consumed by
- `agent/loop.py` — calls place_order() for qualified signals

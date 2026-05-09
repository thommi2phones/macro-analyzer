# M7 — Agent Module CLAUDE.md

## Purpose
The orchestration layer. Runs the scan loop, applies pattern-learned confidence
adjustments, filters signals, routes to execution.

## Files
```
agent/
├── CLAUDE.md    ← you are here
└── loop.py      ← main agent loop
main.py          ← CLI entry point (run, scan, validate, report, etc.)
```

## How the loop works
```
Every 15 minutes (or on-demand via `scan`):
  1. Load PatternProfile from data/trade_history_insights.json (M3 output)
  2. For each ticker in watchlist:
       a. Fetch bars from DataProvider (M1)
       b. Run SignalGenerator rules (M2)
       c. If signal fires → apply confidence boost from PatternProfile
       d. If confidence ≥ threshold → route to Broker (M4)
       e. Send alert via Discord/email (M6)
  3. Log results, update paper P&L
```

## Signal confidence threshold
```yaml
# settings.yaml
agent:
  min_confidence: 0.65    # signals below this are logged but not executed
```

## Pattern confidence boosts (from M3 PatternLearner)
Owner's top setups get a confidence multiplier:
```python
boosts = {
    "falling wedge":           +0.15,
    "cup and handle":          +0.12,
    "symmetrical triangle":    +0.10,
    "breakout":                +0.10,
    "fibonacci retracement":   +0.08,
}
```
These are recalculated each time `analyze-trades` is run.

## Scan profiles
```
macro  — runs on 1W/1D bars, long hold bias
swing  — runs on 4h/1D bars, breakout + Fib setups (primary)
intra  — runs on 1h/15m bars, momentum entries
```

## CLI commands (main.py)
```bash
python3 main.py run      # continuous loop (15 min intervals)
python3 main.py scan     # one cycle, print signals, exit
python3 main.py validate # check env + config
python3 main.py report   # paper trading P&L report
```

## Current state (2026-02-22)
- Loop runs but pattern confidence boosts not yet wired in
- Execution module position sizing not implemented
- 352 image re-run blocked on API credits

## TODO for this module
- [ ] Wire PatternLearner confidence boosts into signal filtering
- [ ] Add position reconciliation at startup (load open Alpaca positions)
- [ ] Add graceful shutdown (close nothing, just stop scanning)
- [ ] Add loop health check (alert if scan misses 2+ consecutive cycles)
- [ ] Add paper P&L tracking to data/live/ on each fill

## Depends on all other modules
M1 Data → M2 Signals → M3 Analysis (offline) → M4 Execution → M6 Alerts

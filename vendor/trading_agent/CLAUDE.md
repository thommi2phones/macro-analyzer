# Trading Agent — Root CLAUDE.md

## What this project is
Python CLI trading agent: chart scanning, Claude vision trade analysis, backtesting,
paper/live execution via Alpaca. Built around the owner's personal trading style
(Fibonacci-heavy, breakout/wedge/channel setups, crypto-heavy watchlist).

## Project layout
```
trading_agent/
├── agent/          M7 — orchestration loop (wires all modules)
├── alerts/         M6 — Discord webhook, email, reporting
├── analysis/       M3 — Claude vision image extractor, pattern learner
├── backtesting/    M5 — vectorbt backtester
├── config/         settings.yaml, rules.yaml
├── data/           M1 — Alpaca/yfinance providers, live streaming
├── execution/      M4 — order router, position sizing, risk management
├── scripts/        utility scripts (review_trades.py, etc.)
├── signals/        M2 — scanner, indicator engine, signal generator
└── main.py         CLI entry point
```

## Running commands (always use python3)
```bash
python3 main.py validate                          # check env + config
python3 main.py scan                              # single scan cycle
python3 main.py run                               # continuous 15-min loop
python3 main.py analyze-trades --dir ./trade_images          # re-analyze images
python3 main.py analyze-trades --dir ./trade_images --force  # force re-run all
python3 main.py backtest --ticker AAPL --timeframe 1d
python3 main.py report
python3 scripts/review_trades.py                  # interactive trade review loop
python3 scripts/review_trades.py --nulls          # only records missing entry/TP
```

## Credentials (.env)
- `ANTHROPIC_API_KEY` — Claude API (vision analysis, claude-opus-4-6)
- `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` — paper trading (PA30PCRE0P06)
- `ALPACA_LIVE_API_KEY` / `ALPACA_LIVE_SECRET_KEY` — live (inactive)
- Paper base URL: `https://paper-api.alpaca.markets`

## Chart markup conventions (CRITICAL for image analysis)
The owner marks up TradingView charts with:
- **WHITE horizontal rays** = ENTRY price
- **ORANGE horizontal rays** = TAKE PROFIT (TP) price
- **BLUE dashed lines** = Key support/resistance levels
- **BLUE solid lines** = Pattern structures (channels, wedges, trend lines)
- TP < entry = SHORT | TP > entry = LONG

## Full chart analysis framework
See `config/chart_analysis_framework.md` — priority-ordered guide for all AI instances.

Priority hierarchy (evaluate in this order):
1. **Pattern** (solid blue lines) — sets directional hypothesis
2. **Fibonacci** (white/yellow/GREEN color-coded, green = critical) — confluence
3. **Blue dashed levels** — historical S/R zones
4. **MACD + TTM squeeze** — primary momentum confirmation
5. **RSI structure** — secondary confirmation (structural, NOT overbought/oversold)
6. **Thanos EMA cluster** — trend strength / volatility compression
7. **SRChannel** — structural gut check

## Owner's trading style
- Heavy Fibonacci — 0.618 confluence is highest priority
- Preferred timeframes: 4h, 1D, 1W (swing/macro)
- Dominant patterns: breakouts, cup & handle, falling wedge, symmetrical triangle, descending channel
- Heavy crypto focus: BTC, XRP, SOL, DOGE, HBAR, SUI + XAUUSD, XAGUSD, TSLA
- Direction: TP < entry = SHORT, TP > entry = LONG
- Extensions (1.272, 1.618) used for TP projection on breakouts

## Known fixes already applied
- `alpaca_provider.py`: hardcoded `feed="sip"` → `feed=self._feed` (free tier needs iex)
- `alpaca_provider.py`: removed unsupported `3d` timeframe
- `settings.yaml`: removed `3d` from swing profile timeframes
- `main.py`: `load_dotenv(override=True)` — shell had empty ANTHROPIC_API_KEY
- Always use `python3` not `python`

## Current status (updated 2026-02-22)
- Image extractor: full framework prompt updated ✅
- Chart analysis framework doc: `config/chart_analysis_framework.md` ✅
- review_trades.py: interactive review script built ✅
- Checkpoint saving: every 10 images to data/checkpoint.json ✅
- Module CLAUDE.md files: all 7 modules done ✅
- 352 images: 106 old records (stale), 246 never processed
- Strategy: analyze images via Claude Code directly (no API cost)
- list_unprocessed.py + save_records.py scripts ready for in-session analysis

## Module CLAUDE.md files
Each module has its own CLAUDE.md with focused context.
Read only the relevant one when working on a specific module.

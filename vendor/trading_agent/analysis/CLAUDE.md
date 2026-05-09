# M3 — Analysis Module CLAUDE.md

## Purpose
Extract structured trade data from chart screenshots using Claude vision,
then learn patterns from the extracted data to inform live scanning confidence.

## Files
```
analysis/
├── CLAUDE.md                         ← you are here
├── trade_history/
│   ├── image_analyzer.py             ← Claude vision extractor (PRIMARY)
│   └── pattern_learner.py            ← Pattern statistics + insights
└── chat_history/
    └── chat_analyzer.py              ← Extract trades from ChatGPT/Claude exports
```

## image_analyzer.py — how it works
1. Loads each image from `./trade_images/`
2. Sends to `claude-opus-4-6` with adaptive thinking + the extraction prompt
3. Prompt teaches Claude the color markup system (white=entry, orange=TP, blue=levels)
4. Returns a `TradeRecord` pydantic model
5. Saves all records to `data/trade_history.json`

## TradeRecord fields (current schema)
```python
ticker: str
direction: str              # "long" | "short"
entry_price: float | None   # WHITE horizontal ray price
exit_price: float | None    # ORANGE horizontal ray price (TP)
stop_loss: float | None     # stop loss if marked
entry_date: str | None      # YYYY-MM-DD
exit_date: str | None
pnl_dollars: float | None
pnl_percent: float | None
timeframe: str | None       # "1h", "4h", "1D", "1W"
setup_type: str | None      # "falling wedge", "breakout", etc.
fib_levels: dict | None     # {"0.618": 159.65, "0.786": 116.0}
key_levels: list[float]     # prices from BLUE dashed lines
indicators_visible: list[str]
win: bool | None            # True=hit TP, False=stopped, None=unknown
reviewed: bool              # human-reviewed via review_trades.py
notes: str | None
image_path: str | None
extracted_at: str           # ISO timestamp
```

## Chart markup conventions (CRITICAL)
- **WHITE horizontal rays** = ENTRY price
- **ORANGE horizontal rays** = TAKE PROFIT (TP)
- **BLUE dashed lines** = Key S/R levels (not entry/TP)
- TP < entry → SHORT | TP > entry → LONG

## Running analysis
```bash
# Re-analyze all images with latest prompt (after prompt changes)
python3 main.py analyze-trades --force

# Only process new/unprocessed images (default, incremental)
python3 main.py analyze-trades

# Interactive human review loop (correct extraction errors)
python3 scripts/review_trades.py           # unreviewed only
python3 scripts/review_trades.py --nulls   # records missing entry or TP
python3 scripts/review_trades.py --all     # everything
```

## Current state (2026-02-22)
- 352 images in `./trade_images/`
- 106 records in `data/trade_history.json` — mostly null entry/TP (old bad prompt)
- Prompt updated to know white=entry, orange=TP ✅
- BLOCKED: Anthropic API credits depleted — top up at console.anthropic.com
- After credits: run `python3 main.py analyze-trades --force`
- After re-run: run `python3 scripts/review_trades.py --nulls` for human corrections

## TODO for this module
- [ ] Add checkpoint saving every 10 images (crash recovery)
- [ ] Add confidence score to TradeRecord (0.0–1.0, how sure Claude was)
- [ ] Add multi-TP support (some charts have multiple orange rays)
- [ ] Improve pattern_learner.py to use reviewed records preferentially

## Output consumed by
- `agent/loop.py` — applies pattern confidence adjustments to live signals
- `backtesting/engine.py` — validates patterns against historical data

# Vendored: trading_agent

Source-only snapshot copied 2026-05-09 from
`/Users/thom/Documents/Personal/Code Projects/trading_agent/`.

**Status:** read-only reference. Do NOT import from this directory in
production code. Files are ported selectively into
`src/macro_positioning/manual/` per the manual-input-layer plan.

**Excluded from the snapshot:** `.git/`, `node_modules/`, `dashboard/`
(710MB of node_modules), `trade_images/` (142MB binary samples),
`data_cache/`, `logs/`, `__pycache__/`, virtualenvs.

**What's actually used:**

| File | Ported to |
|---|---|
| `analysis/trade_history/image_analyzer.py` | `src/macro_positioning/manual/models.py` (TradeRecord) + Piece 2 vision (prompt only) |
| `analysis/chat_history/chat_analyzer.py` | `src/macro_positioning/manual/chat_parser.py` |
| `config/chart_analysis_framework.md` | `config/manual_chart_framework.md` |
| `signals/inbox_processor.py` | reference only — TradingView webhook ingestion deferred |

See `~/.claude/plans/manual-input-layer-also-hazy-island.md` for context.

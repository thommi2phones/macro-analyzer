# Current State

_Last updated: 2026-06-09 (extraction complete + forward capturer live + accuracy backtester running, metrics need refinement)_

> **Roadmap to completion:** see [`MASTER-PLAN.md`](MASTER-PLAN.md) — milestones M1–M5, timelines, and the full to-do list to a usable state. This file is the per-session handoff; MASTER-PLAN is the destination.

## Active Task

**Macro Analyzer — Telegram trade-call intelligence.** Pull KOL chart calls from
5 Telegram channels → extract structured calls (chart-vision) → score per-source
accuracy → conviction/themes → ultimately "when to buy." This session: rebuilt &
validated the vision extraction, ran the FULL corpus, stood up the live forward
capturer, and got the accuracy backtester running on the full dataset.

Branch: `claude/streams-live` (main repo at project root). Uncommitted.

## Progress

- [x] Telegram poller (read-only, 5 channels, album-group, author-based dedupe)
- [x] **Vision extraction rebuilt & LOCKED** — caption-aware, call_type/direction/
      bias/trade_stage; validated **91–100% primary fields** on 173 verified charts
- [x] **Full corpus extracted** — all ~6,263 charts with the locked prompt (~$48 total)
- [x] **Training corpus** — 6,291 weak + 191 gold labels (auto-banked on each verify)
- [x] **Forward capturer LIVE** — listener + auto-extract in one process
- [x] **Accuracy backtester DONE & refined** — 1,494 calls scored; metrics now
      decision-grade: `setup_win_rate` (target-before-stop) PRIMARY, winsorized R
      (`_MAX_SANE_R=8`), min-sample gate (`_MIN_SAMPLE=10`, `meaningful` flag), and
      market-relative ALPHA (call ret − BTC, beta-stripped). Endpoint
      `/api/manual/accuracy/sources` returns all of it. Run: `backtest_calls()` then
      `source_accuracy(window_days=N)`. Results: OG Whales 81% setup; on ALPHA the
      ranking FLIPS — Market Traders +5.0% / Big_Nuts +3.8% are the real outperformers.
- [ ] **NEXT ACTION — wire conviction (#2):** `learning/source_themes.py` now runs on
      real call_type/bias/direction; fold per-source accuracy (setup_win + alpha) into
      conviction; re-enable the accuracy badge on S6 (`web/inbox.jsx` TrustedAuthorCard,
      currently hidden) now that numbers are trustworthy.
- [ ] Themes + timing ("when to buy") — the goal
- [ ] Housekeeping: launchd plist for listener durability; commit to branch

## Files Touched This Session

- `config/manual_chart_framework.md` — the LOCKED extraction prompt (SECTION 10 = JSON schema)
- `src/macro_positioning/manual/vision.py` — `caption=` param + prompt caching + list-response fix
- `src/macro_positioning/manual/vision_drainer.py` — transient-vs-permanent error split, image-ext filter
- `src/macro_positioning/manual/telegram_poller.py` — `_schedule_extract()` (listener auto-extract)
- `src/macro_positioning/prices/symbol_map.py` — `resolve_symbol`, tracked-crypto allowlist, CMC overrides
- `src/macro_positioning/learning/call_accuracy.py` — backtester; `_extract_call` now filters by call_type
- `src/macro_positioning/api/manual_input.py` — `/verify/list`, `/verify/mark` (+training-label append), `/accuracy/sources`
- `src/macro_positioning/api/main.py` — CORS for verify tooling
- `web/verify.html` — extraction-QA review UI (paginated, ground-truth form)
- `web/inbox.jsx` + `web/streams.jsx` — I3 panel moved to S6 (accuracy badge currently hidden)
- memory: `feedback_trade_call_types`, `feedback_multistage_trades`, `reference_kol_slang`

## Key Context

- **`setup_win_rate` is the trustworthy accuracy metric, NOT `dir_win`.** dir_win =
  fixed-horizon buy-and-hold = market beta (crypto down-window). OG Whales 12% dir
  but 81% setup is the proof. Lead with setup-resolution; the beta fix = alpha measure.
- **Extraction prompt is LOCKED.** trade_stage is best-effort secondary (88%); core
  fields 91–100%. Rules in framework + 3 memory files. Caption is essential context.
- **Scope split:** scoring/conviction filter to Coinbase-tradeable (`resolve_symbol`);
  TRAINING keeps ALL charts incl. shitcoins. ~1,429 calls were unpriceable (excluded).
- **Cost gotcha:** prompt cache races at high concurrency (~$0.016/call) → WARM cache
  once + CONCURRENCY=4 → ~$0.006/call. Recipe in `/tmp/redrain_full.py` (ephemeral).
- **Running processes (won't survive reboot):** listener `nohup` pid in
  `/tmp/tg-listener.pid` (log `/tmp/tg-listener.log`); API server `:8000` (no --reload).
- **DB backups:** `data/macro_positioning.db.pre-fullcorpus`, `.pre-redrain`, `.pre-canonical-fix`.
- Plan file: `~/.claude/plans/i-think-we-should-curried-bengio.md` (accuracy layer).

## Next Steps

1. **Refine accuracy metrics in `call_accuracy.py`** (the in-progress item): winsorize
   r_multiple, add min-sample gate (~10), validate ticker (drop junk), add market-relative
   alpha (call return − BTC over same window). Re-run `backtest_calls()` + `source_accuracy()`.
2. Wire conviction/themes on the real extractions; re-enable accuracy badge on S6.
3. Themes + timing layer.
4. launchd plist for listener; commit session work.

## Blocked / Waiting

None hard-blocked. (Anthropic credits currently near-$0 again after full corpus — only
matters if re-extracting; not needed for accuracy/conviction work which uses yfinance + DB.)

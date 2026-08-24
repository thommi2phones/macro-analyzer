# Open Questions & Blockers

Active items waiting on user input or external action.

---

## Alerts — Telegram bot token (blocks delivery)

- [2026-08-24] The alerts layer is built, tested, replayed against August
  history, and scheduled hourly (`com.macro.alert-watch`). It is
  **deriving and recording alerts but cannot deliver them** until the
  operator creates a Telegram bot — this is the one step that can't be
  automated, because @BotFather only talks to a human:

  1. Message **@BotFather** → `/newbot` → copy the token
  2. Send the new bot any message (bots cannot open a chat with you)
  3. `MPA_TELEGRAM_BOT_TOKEN=<token>` in `.env`, then
     `python scripts/alert_watch.py --whoami` to print the chat id
  4. `MPA_TELEGRAM_ALERT_CHAT_ID=<chat id>` in `.env`
  5. Verify with `python scripts/alert_watch.py --test-send`

  Nothing fired in the meantime is lost: undelivered alerts are retried
  for `alert_redelivery_window_hours` (24h) after the token lands.

---

## ML / learning loop scope

- [2026-05-09] Priority order for the 7 ML-loop items in STATE.md
  "Next Steps — ML / Learning Loop"? Source attribution aggregator is the
  smallest first move; correlation analysis needs more closed trades; full
  retraining needs multi-month corpus.

- [2026-05-09] When do we wire the FIRST real LLM-backed agent? Now
  partially answered: `chart_vision` goes Gemini-via-existing-brain/vision.py
  (manual input chat owns it). For `regime_classifier` and
  `narrative_synthesizer` — likely also Gemini. The deep_research agent
  (Perplexity/OpenAI) is a separate slot to design later under budget
  guards. See DECISIONS 2026-05-09 "LLM stack" entry.

## Deployment

- [2026-05-09] Deployment target for macro-analyzer — Render still the call
  (per D-2026-05-08-003)? Needed before the tactical-gate endpoint can be
  tested live with `Trading-Agent-V1-CODEX`.

## Resolved this session (kept for record)

- ~~[2026-05-09] composer.py stub_components / technical_structure~~
  RESOLVED in Phase 6c. Removed from stubs (technical_scorer now real);
  test updated to reflect new state.

## Deferred (not blocking; tracked elsewhere)

- COT data connector — Phase C in workstreams, deferred behind ML-loop work
  and the manual input layer.
- 4h/12h intraday timeframes — needs intraday yfinance fetch + per-tf
  feature compute. Tracked in STATE.md "Next Steps".

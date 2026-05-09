# Open Questions & Blockers

Active items waiting on user input or external action.

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

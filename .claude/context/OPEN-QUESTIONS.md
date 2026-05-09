# Open Questions & Blockers

Active items waiting on user input or external action.

---

## ML / learning loop scope

- [2026-05-09] Priority order for the 7 ML-loop items in STATE.md
  "Next Steps — ML / Learning Loop"? Source attribution aggregator is the
  smallest first move; correlation analysis needs more closed trades; full
  retraining needs multi-month corpus.

- [2026-05-09] When do we wire the FIRST real LLM-backed agent
  (`regime_classifier` or `narrative_synthesizer`)? Burns tokens. Probably
  wait until manual input layer ships so dropped charts + notes also feed
  the synth corpus.

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

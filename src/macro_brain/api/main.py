"""macro-brain HTTP surface.

Endpoints:
    GET  /health                         service check
    GET  /regime/current                 current active regime read
    POST /score                          compose a TradeScore from a SetupContext
    POST /synthesize                     run narrative_synthesizer over documents

Phase 4 endpoints are minimal but functional. macro-analyzer will call
these once macro-brain is deployed (Phase 7).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import FastAPI

from macro_brain.agents.narrative_synthesizer.synthesizer import (
    SynthesisInput,
    SynthesisOutput,
    synthesize_stub,
)
from macro_brain.agents.regime_classifier.classifier import classify_regime_stub
from macro_brain.orchestrator.composer import compose
from macro_brain.types import RegimeRead, SetupContext, TradeScore


app = FastAPI(
    title="macro-brain",
    version="0.1.0",
    description="Scoring engine for the Macro Positioning Analyzer (Phase 4 bootstrap).",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "macro-brain", "phase": "4-bootstrap"}


# In-memory cache of the most recent regime classification. Production
# will pull this from macro-analyzer's macro_regimes table; this in-mem
# version is enough for Phase 4 single-instance use.
_LATEST_REGIME: RegimeRead | None = None


@app.get("/regime/current", response_model=RegimeRead)
def regime_current(hint: str | None = None) -> RegimeRead:
    """Return the current regime classification.

    `hint` (optional): if no regime cached, generate a stub regime from
    this thesis-regime hint. Useful for first-boot before any real
    classification has run.
    """
    global _LATEST_REGIME
    if _LATEST_REGIME is None:
        _LATEST_REGIME = classify_regime_stub(hint_thesis_regime=hint)
    return _LATEST_REGIME


@app.post("/regime/refresh", response_model=RegimeRead)
def regime_refresh(hint: str | None = None) -> RegimeRead:
    """Re-run the regime classifier (currently a stub)."""
    global _LATEST_REGIME
    _LATEST_REGIME = classify_regime_stub(hint_thesis_regime=hint)
    return _LATEST_REGIME


@app.post("/score", response_model=TradeScore)
def score(setup: SetupContext) -> TradeScore:
    """Compose a TradeScore from an incoming SetupContext.

    If `setup.active_regime` is missing, fall back to the cached
    /regime/current. (Future: trigger a fresh regime classification
    if the cache is older than N minutes.)
    """
    if setup.active_regime is None:
        setup.active_regime = regime_current()
    return compose(setup)


@app.post("/synthesize", response_model=SynthesisOutput)
def synthesize(payload: SynthesisInput) -> SynthesisOutput:
    """Run the narrative synthesizer (currently stubbed)."""
    return synthesize_stub(payload)

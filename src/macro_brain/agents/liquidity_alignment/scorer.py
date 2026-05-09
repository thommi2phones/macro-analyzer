"""Liquidity Alignment — heuristic, no LLM.

Reads `setup.liquidity_features` (preloaded by the scoring runner from
the FRED provider; NFCI / ANFCI series) and emits a SubScore for
`liquidity_alignment`.

NFCI convention (Chicago Fed): negative = looser-than-average financial
conditions; positive = tighter. We score on:
  - 4-week change (easing trajectory matters more than absolute level)
  - regime_bullish flag: when the active thesis is bullish, easing
    aligns (high score); when bearish, tightening aligns.

Shape:
  {
    "nfci_latest":    float | None,
    "nfci_4w_change": float | None,
    "regime_bullish": bool,
    "source":         str,    # "fred:NFCI" | "missing"
  }

Missing FCI series → 0.5 with note.
"""

from __future__ import annotations

import math

from macro_brain.agents._heuristic_log import with_log
from macro_brain.types import SetupContext, SubScore

VERSION = "liquidity_alignment@v1"
_SCALE = 0.5  # NFCI moves ~0.5 over a meaningful liquidity shift


def _compute(feats: dict) -> SubScore:
    nfci = feats.get("nfci_latest")
    delta = feats.get("nfci_4w_change")
    regime_bullish = bool(feats.get("regime_bullish", True))
    source = feats.get("source") or "missing"

    if delta is None and nfci is None:
        return SubScore(
            component="liquidity_alignment",
            value=0.5,
            contributing_features={"defined": 0.0},
            notes=f"No FCI data available ({source}).",
        )

    # easing = NFCI falling. easing_signal > 0 when conditions are easing.
    easing_signal = 0.0
    if delta is not None:
        easing_signal += -float(delta)
    if nfci is not None:
        easing_signal += -float(nfci) * 0.5

    if not regime_bullish:
        easing_signal = -easing_signal

    value = 0.5 + 0.5 * math.tanh(easing_signal / _SCALE)
    value = max(0.0, min(1.0, value))

    direction = "easing" if (delta is not None and delta < 0) else (
        "tightening" if (delta is not None and delta > 0) else "flat"
    )
    return SubScore(
        component="liquidity_alignment",
        value=value,
        contributing_features={
            "nfci_latest": float(nfci) if nfci is not None else 0.0,
            "nfci_4w_change": float(delta) if delta is not None else 0.0,
            "regime_bullish": 1.0 if regime_bullish else 0.0,
            "easing_signal": float(easing_signal),
        },
        notes=f"NFCI {direction} (Δ4w={delta if delta is not None else 'n/a'}); regime {'bullish' if regime_bullish else 'bearish'}.",
    )


def score_liquidity_alignment(setup: SetupContext) -> SubScore:
    feats = setup.liquidity_features or {}
    return with_log(
        agent_name="liquidity_alignment",
        version=VERSION,
        input_features=feats,
        fn=lambda: _compute(feats),
    )

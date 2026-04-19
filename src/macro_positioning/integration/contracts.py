"""Versioned contracts between macro-analyzer and tactical-executor.

These schemas are the CANONICAL source of truth for both repos.

On the macro-analyzer side: directly used by FastAPI endpoints.
On the tactical-executor side: mirrored in /integration/macro_schema.json
(exported from this file via scripts/export_integration_schema.py).

When either side needs to change the contract:
  1. Change the Pydantic model here
  2. Bump CONTRACT_VERSION
  3. Regenerate JSON schema export
  4. Open a cross-repo PR that updates both sides
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from macro_positioning.core.models import utc_now

# Bump this any time the schema changes (non-backwards-compatible change)
CONTRACT_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# MacroPositioningView — what tactical pulls from macro
# ---------------------------------------------------------------------------

class GateSuggestion(BaseModel):
    """Recommendation to the tactical-executor's decision gate."""
    allow_long: bool = True
    allow_short: bool = True
    size_multiplier: float = Field(default=1.0, ge=0.0, le=2.0)
    notes: str = ""


class MacroPositioningView(BaseModel):
    """Per-asset directional macro view. Consumed by tactical decision gate.

    Endpoint: GET /positioning/view?asset={ticker}
    """
    contract_version: str = CONTRACT_VERSION
    asset: str
    asset_class: str = ""
    direction: Literal["bullish", "bearish", "neutral", "mixed", "watchful", "unknown"] = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    horizon: str = ""
    source_theses: list[str] = Field(default_factory=list, description="Thesis IDs backing this view")
    regime: str = ""
    last_updated: datetime = Field(default_factory=utc_now)
    gate_suggestion: GateSuggestion = Field(default_factory=GateSuggestion)


# ---------------------------------------------------------------------------
# MacroOutcomeReport — what tactical posts back to macro
# ---------------------------------------------------------------------------

class MacroViewSnapshot(BaseModel):
    """Snapshot of the macro view at the time of trade entry."""
    direction: str = ""
    confidence: float = 0.0
    source_theses: list[str] = Field(default_factory=list)


class MacroOutcomeReport(BaseModel):
    """Trade outcome feedback from tactical → macro source-scoring.

    Endpoint: POST /source-scoring/outcome
    """
    contract_version: str = CONTRACT_VERSION
    trade_id: str
    symbol: str
    direction: Literal["long", "short"]
    entry_timestamp: datetime
    exit_timestamp: datetime
    outcome: Literal["win", "loss", "breakeven"]
    pnl_r: float = Field(..., description="R-multiple (risk units gained/lost)")
    macro_view_at_entry: MacroViewSnapshot


class MacroOutcomeAck(BaseModel):
    """Response from macro after recording a trade outcome."""
    recorded: bool
    sources_credited: list[str] = Field(default_factory=list)
    source_weights_updated: dict[str, dict] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# TacticalClient — what the macro side uses to talk TO tactical (optional)
# ---------------------------------------------------------------------------

class TacticalClient:
    """Thin HTTP client for calling the tactical-executor from macro side.

    Used when macro wants to push regime changes, flag invalidations, or
    query active tactical positions. Not critical for MVP — Phase 1 is
    primarily tactical-pulls-from-macro.
    """

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def health(self) -> dict:
        with httpx.Client(timeout=self.timeout) as client:
            r = client.get(f"{self.base_url}/health")
            r.raise_for_status()
            return r.json()

    def list_active_setups(self) -> list[dict]:
        """List active tactical setups (for cross-referencing macro view)."""
        with httpx.Client(timeout=self.timeout) as client:
            r = client.get(f"{self.base_url}/events/latest")
            r.raise_for_status()
            return r.json()

    def notify_regime_change(self, regime: str, direction_shift: dict) -> dict:
        """Inform tactical side of a regime change so it can re-evaluate."""
        payload = {
            "regime": regime,
            "direction_shift": direction_shift,
            "timestamp": utc_now().isoformat(),
        }
        with httpx.Client(timeout=self.timeout) as client:
            r = client.post(f"{self.base_url}/macro/regime-update", json=payload)
            r.raise_for_status()
            return r.json()

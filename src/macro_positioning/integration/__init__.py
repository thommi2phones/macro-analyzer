"""Integration layer with tactical-executor (trading-agent-v1-codex).

This module owns the contracts between macro-analyzer and the tactical
execution layer. Keep schemas here so both repos can reference a single
source of truth (schemas can be synced via JSON schema export).
"""

from macro_positioning.integration.contracts import (
    MacroOutcomeReport,
    MacroPositioningView,
    TacticalClient,
)

__all__ = [
    "MacroPositioningView",
    "MacroOutcomeReport",
    "TacticalClient",
]

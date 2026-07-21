"""Signal extraction layer.

Turns ingested documents (manual drops, insider events, news, RSS) into
structured `Signal` rows the scoring composer can aggregate per asset
into a directional positioning bias.

Architecture:
    document  ──►  router.choose_extractor(doc)  ──►  Signal[]  ──►  repository
                       │
                       ├── insider_extractor   (rule-based, structured docs)
                       ├── llm_extractor       (Gemini/Claude, prose docs)
                       └── (future) vision_extractor (chart screenshots)

The composer (scoring/runner.py) reads the `signals` table and rolls
signals up per asset_ticker into a weighted positioning bias.
"""

from macro_positioning.signals.base import (
    Signal,
    SignalSide,
    SignalHorizon,
    SignalCatalystType,
    SignalStatus,
    ExtractorProtocol,
    ExtractionResult,
)

__all__ = [
    "Signal",
    "SignalSide",
    "SignalHorizon",
    "SignalCatalystType",
    "SignalStatus",
    "ExtractorProtocol",
    "ExtractionResult",
]

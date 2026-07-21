"""Signal model + extractor protocol.

`Signal` mirrors the `signals` table 1:1 — every persisted column is a
field here. The scoring composer pulls Signal rows back out via
`repository.load_active_signals_for_ticker()`.

Extractors implement `ExtractorProtocol.extract(document)` and return an
`ExtractionResult` so the runner can record both successful signals
AND the audit trail (latency, model used, errors) for empty/failed runs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Iterable, Optional, Protocol

from pydantic import BaseModel, Field, field_validator


# ── Enums (kept as string enums so SQLite values stay human-readable) ────────


class SignalSide(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    HEDGE = "HEDGE"      # short against an existing long, or vol-hedge
    EXIT = "EXIT"        # close an existing position
    TRIM = "TRIM"        # reduce existing position
    ADD = "ADD"          # add to existing position (direction implied by prior signal)
    WATCH = "WATCH"      # on radar, no directional bias yet
    AVOID = "AVOID"      # explicit do-not-trade

    @classmethod
    def coerce(cls, raw: Optional[str]) -> "SignalSide":
        if raw is None:
            return cls.WATCH
        u = str(raw).strip().upper()
        # Common aliases from source-native vocab
        aliases = {
            "BUY": cls.LONG, "BULLISH": cls.LONG, "PURCHASE": cls.LONG,
            "NEW": cls.LONG, "GROWN": cls.ADD,
            "SELL": cls.SHORT, "BEARISH": cls.SHORT, "SALE": cls.TRIM,
            "EXITED": cls.EXIT, "CLOSE": cls.EXIT,
        }
        if u in aliases:
            return aliases[u]
        try:
            return cls(u)
        except ValueError:
            return cls.WATCH


class SignalHorizon(str, Enum):
    INTRADAY = "intraday"      # < 1 day
    SWING = "swing"            # 1d–4w
    POSITION = "position"      # 1m–6m
    STRATEGIC = "strategic"    # > 6m

    @classmethod
    def from_days(cls, days: Optional[int]) -> Optional["SignalHorizon"]:
        if days is None:
            return None
        if days < 1:
            return cls.INTRADAY
        if days <= 28:
            return cls.SWING
        if days <= 180:
            return cls.POSITION
        return cls.STRATEGIC


class SignalCatalystType(str, Enum):
    EARNINGS = "earnings"
    MACRO_PRINT = "macro_print"     # CPI, NFP, FOMC, etc.
    POLITICAL = "political"         # legislation, lobbying, gov contract
    TECHNICAL = "technical"         # chart pattern, level break
    FLOW = "flow"                   # insider buy, 13D, unusual options
    CORPORATE = "corporate"         # M&A, buyback, dividend, guidance
    OTHER = "other"


class SignalStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"


# ── Signal model ────────────────────────────────────────────────────────────


class Signal(BaseModel):
    """One directional signal extracted from one document.

    Persisted as a row in the `signals` table. The composer aggregates
    active signals per asset to derive positioning bias.
    """

    # Identity
    signal_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    document_id: str
    extracted_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    extraction_run_id: Optional[str] = None

    # Asset / instrument
    asset_ticker: str
    asset_class: Optional[str] = None       # equity|etf|crypto|fx|rates|commodity|option
    secondary_tickers: list[str] = Field(default_factory=list)
    instrument_detail: dict[str, Any] = Field(default_factory=dict)

    # Direction / sizing
    side: SignalSide = SignalSide.WATCH
    conviction: float = 1.0                 # normalized 0..5
    conviction_raw: Optional[str] = None    # source-native form
    position_size_hint: Optional[float] = None
    position_size_unit: Optional[str] = None
    horizon: Optional[SignalHorizon] = None
    horizon_days: Optional[int] = None

    # Levels
    entry_zone_low: Optional[float] = None
    entry_zone_high: Optional[float] = None
    stop_loss: Optional[float] = None
    target_1: Optional[float] = None
    target_2: Optional[float] = None
    invalidation: Optional[str] = None

    # Thesis context
    thesis_summary: Optional[str] = None
    thesis_tags: list[str] = Field(default_factory=list)
    macro_regime_tags: list[str] = Field(default_factory=list)
    catalyst_type: Optional[SignalCatalystType] = None
    catalyst_date: Optional[str] = None
    catalyst_summary: Optional[str] = None

    # Provenance
    source_slug: str
    source_channel: Optional[str] = None
    author_id: Optional[str] = None
    author_trust_weight: Optional[float] = None
    source_trust_weight: Optional[float] = None

    # Extractor metadata
    extractor_name: str
    extractor_version: str = "v1"
    extractor_confidence: Optional[float] = None    # 0..1
    model_provider: Optional[str] = None
    model_name: Optional[str] = None
    raw_excerpt: Optional[str] = None
    extraction_call_id: Optional[str] = None

    # Lifecycle
    status: SignalStatus = SignalStatus.ACTIVE
    expires_at: Optional[str] = None
    superseded_by: Optional[str] = None

    # Weighting snapshot (composer can override)
    weighted_score: Optional[float] = None

    # Audit
    latency_ms: Optional[float] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    error_message: Optional[str] = None

    @field_validator("asset_ticker")
    @classmethod
    def _upper_ticker(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("conviction")
    @classmethod
    def _bound_conviction(cls, v: float) -> float:
        return max(0.0, min(5.0, float(v)))

    def compute_weighted_score(self) -> float:
        """Composite = conviction × source_trust × author_trust.

        Composer can recompute with time-decay; this is the snapshot at
        extract time so historical signals stay reproducible.
        """
        src = self.source_trust_weight if self.source_trust_weight is not None else 1.0
        auth = self.author_trust_weight if self.author_trust_weight is not None else 1.0
        return self.conviction * src * auth


# ── Extractor protocol ──────────────────────────────────────────────────────


@dataclass
class ExtractionResult:
    """Outcome of running one extractor against one document.

    Even when zero signals are produced we keep the audit trail so the
    runner doesn't retry indefinitely and so we can debug why a given
    doc didn't yield a signal.
    """

    document_id: str
    extractor_name: str
    extractor_version: str
    status: str                       # success|no_signal|error|skipped
    signals: list[Signal] = field(default_factory=list)
    error_message: Optional[str] = None
    latency_ms: Optional[float] = None


class ExtractorProtocol(Protocol):
    """Each extractor knows how to turn one doc into 0..N Signals.

    `applies_to(doc)` is the router's question: this lets each extractor
    self-declare which docs it can handle. Order in `router.EXTRACTORS`
    decides precedence on ties.
    """

    name: str
    version: str

    def applies_to(self, document: dict) -> bool: ...

    def extract(
        self,
        document: dict,
        *,
        run_id: Optional[str] = None,
    ) -> ExtractionResult: ...

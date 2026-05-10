"""Pydantic models for the manual input layer.

`TradeRecord` is ported from
`vendor/trading_agent/analysis/trade_history/image_analyzer.py` — the canonical
extracted-features schema for a chart. In Piece 1 it's the *target* shape;
Piece 2 (Gemini vision) populates it.

`ManualInputPayload` is what the SPA POSTs to `/api/manual/ingest`.
`AuthorRef` is a small helper that round-trips with `input_authors` rows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ── Author / channel attribution ─────────────────────────────────────────────


class AuthorRef(BaseModel):
    """First-class author/channel attribution for a manual input.

    `display_name` and `channel` together produce the slug used as
    `author_id` (see `manual.authors.slugify_author`).
    """

    display_name: str
    channel: Optional[str] = None  # "BWatch chat", "self", "TradingView public"
    channel_type: Optional[str] = None  # telegram | discord | self | twitter | tradingview | other
    notes: Optional[str] = None


# ── User-supplied metadata per drop ──────────────────────────────────────────


class ManualMetadata(BaseModel):
    """User-controlled metadata that rides on every drop.

    Auto-extracted suggestions (ticker, side guess) flow through the same
    shape so the SPA can pre-fill and let the user confirm/correct each.
    """

    ticker: Optional[str] = None
    side: Optional[str] = None  # LONG | SHORT | WATCH
    conviction: Optional[int] = None  # 1..5
    timeframe: Optional[str] = None  # 1H | 4H | 1D | 1W
    note: Optional[str] = None  # one-line blurb in addition to the body text

    @field_validator("side")
    @classmethod
    def _norm_side(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        u = v.strip().upper()
        if u in ("LONG", "SHORT", "WATCH"):
            return u
        if u in ("BUY", "BULLISH"):
            return "LONG"
        if u in ("SELL", "BEARISH"):
            return "SHORT"
        return None

    @field_validator("conviction")
    @classmethod
    def _bound_conv(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return None
        return max(1, min(5, int(v)))

    @field_validator("timeframe")
    @classmethod
    def _norm_tf(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        u = v.strip().upper().replace(" ", "")
        return u if u in ("1H", "4H", "1D", "1W") else None


# ── Submission payload ───────────────────────────────────────────────────────


class ManualInputPayload(BaseModel):
    """Body of a `POST /api/manual/ingest` request.

    The SPA serializes this as JSON alongside an optional uploaded file
    (handled separately as multipart). For preview/dry-run, the same
    payload is posted to `/api/manual/preview`.
    """

    text: str = ""
    metadata: ManualMetadata = Field(default_factory=ManualMetadata)
    author: AuthorRef
    # Server-populated when files are uploaded. Clients leave both empty.
    # `attachment_path` = first image (back-compat with single-image
    # consumers); `attachment_paths` = full ordered list, one per uploaded
    # file. A drop with N images sets attachment_paths to length N and
    # attachment_path to attachment_paths[0].
    attachment_path: Optional[str] = None
    attachment_paths: list[str] = Field(default_factory=list)


# ── Extracted-features schema (Piece 2 fills this) ───────────────────────────
# Ported verbatim from vendor/trading_agent/analysis/trade_history/image_analyzer.py.
# Kept here so the DB column `documents.extracted_features_json` has a stable
# shape from day one even though Piece 1 doesn't populate it.


class TradeRecord(BaseModel):
    """Structured trade data extracted from a chart screenshot.

    Source of truth for what Piece 2 vision returns. Stored as JSON in
    `documents.extracted_features_json`.
    """

    ticker: str
    direction: str  # "long" | "short"
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    stop_loss: Optional[float] = None
    entry_date: Optional[str] = None  # YYYY-MM-DD
    exit_date: Optional[str] = None
    pnl_dollars: Optional[float] = None
    pnl_percent: Optional[float] = None

    timeframe: Optional[str] = None  # "1m","15m","1h","4h","1D","1W"
    setup_type: Optional[str] = None
    fib_levels: Optional[dict] = None
    key_levels: list[float] = Field(default_factory=list)
    indicators_visible: list[str] = Field(default_factory=list)

    macd_state: Optional[str] = None
    rsi_state: Optional[str] = None
    confluence_score: Optional[int] = None  # 1..5
    bias: Optional[str] = None  # bullish | bearish | neutral
    invalidation_level: Optional[float] = None

    win: Optional[bool] = None
    reviewed: bool = False
    notes: Optional[str] = None
    image_path: Optional[str] = None
    extracted_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

    @field_validator("direction")
    @classmethod
    def _norm_direction(cls, v: str) -> str:
        v = v.lower().strip()
        if v in ("long", "buy", "bullish"):
            return "long"
        if v in ("short", "sell", "bearish"):
            return "short"
        return v

    @field_validator("bias")
    @classmethod
    def _norm_bias(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.lower().strip()
        if v in ("bullish", "bull", "long"):
            return "bullish"
        if v in ("bearish", "bear", "short"):
            return "bearish"
        return "neutral"


# ── Preview response ─────────────────────────────────────────────────────────


class PreviewResponse(BaseModel):
    """Returned by `POST /api/manual/preview`. No persistence."""

    detected_tickers: list[str] = Field(default_factory=list)
    suggested_tags: list[str] = Field(default_factory=list)
    suggested_agents: list[str] = Field(default_factory=list)
    suggested_author_id: Optional[str] = None  # slug match if author display+channel hit


# ── Ingest response ──────────────────────────────────────────────────────────


class IngestResponse(BaseModel):
    document_id: str
    author_id: str
    detected_tickers: list[str]
    tags: list[str]
    pending_vision: bool

"""Rule-based extractor for structured insider/event documents.

Insider docs land in the `documents` table via the insiders.ingest.funnel(),
which carries the source-native ticker/side/conviction in
`user_metadata_json`. This extractor reads those fields directly — no LLM
needed — and emits one Signal per (document, ticker).

Per-channel conviction defaults mirror insiders/ingest.py::CONVICTION_DEFAULTS
but the Signal.conviction field also incorporates author_trust_weight
captured at extract time, so the composer can apply learning loop
adjustments without re-running extraction.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from time import perf_counter
from typing import Optional

from macro_positioning.core.settings import settings
from macro_positioning.signals.base import (
    ExtractionResult,
    Signal,
    SignalCatalystType,
    SignalHorizon,
    SignalSide,
)
from macro_positioning.signals.router import is_structured_insider

log = logging.getLogger(__name__)


# Source-channel trust weight defaults. Distinct from author_trust_weight
# (which is per-individual): this is "how much do we trust the *channel*."
# Section-16 (form4) > Senate PTR > House PTR > social.
_CHANNEL_TRUST = {
    "corp_insider": 1.5,
    "gov_insider": 1.2,
    "large_holder": 1.4,    # 13D/G/F
    "fed_spend": 0.8,       # USAspending — slow signal
    "lobbying": 0.6,        # LDA — directional hints not trade signals
    "social": 0.5,          # ape/stocktwits/uw — noisy
}


def _timeframe_to_horizon(tf: Optional[str]) -> Optional[SignalHorizon]:
    if not tf:
        return None
    tf = tf.upper()
    if tf in ("1H", "4H"):
        return SignalHorizon.INTRADAY
    if tf == "1D":
        return SignalHorizon.SWING
    if tf == "1W":
        return SignalHorizon.POSITION
    return None


def _author_trust(author_id: Optional[str]) -> Optional[float]:
    if not author_id:
        return None
    try:
        with sqlite3.connect(settings.sqlite_path) as conn:
            row = conn.execute(
                "SELECT trust_weight FROM input_authors WHERE author_id = ?",
                (author_id,),
            ).fetchone()
        return float(row[0]) if row and row[0] is not None else None
    except Exception:
        return None


class InsiderExtractor:
    """Rule-based extractor for structured insider/event docs."""

    name = "insider_extractor"
    version = "v1"

    def applies_to(self, document: dict) -> bool:
        return is_structured_insider(document)

    def extract(
        self,
        document: dict,
        *,
        run_id: Optional[str] = None,
    ) -> ExtractionResult:
        t0 = perf_counter()
        doc_id = document["document_id"]

        try:
            meta = json.loads(document.get("user_metadata_json") or "{}")
        except (TypeError, ValueError) as exc:
            return ExtractionResult(
                document_id=doc_id,
                extractor_name=self.name,
                extractor_version=self.version,
                status="error",
                error_message=f"user_metadata_json invalid: {exc}",
                latency_ms=(perf_counter() - t0) * 1000,
            )

        try:
            tags = json.loads(document.get("tags_json") or "{}")
        except (TypeError, ValueError):
            tags = {}

        user = meta.get("user") or {}
        resolved = meta.get("resolved") or {}
        channel = meta.get("channel") or "insider"

        # Primary ticker comes from user (corrections win) then resolved (auto-fill).
        primary_ticker = user.get("ticker") or resolved.get("ticker")

        # Full ticker list — emit one signal per ticker in the doc. The
        # funnel writes the canonical $TICKER list into tags_json.tickers.
        all_tickers: list[str] = []
        if primary_ticker:
            all_tickers.append(primary_ticker.upper())
        for t in tags.get("tickers") or []:
            t_up = t.upper()
            if t_up not in all_tickers:
                all_tickers.append(t_up)

        if not all_tickers:
            return ExtractionResult(
                document_id=doc_id,
                extractor_name=self.name,
                extractor_version=self.version,
                status="no_signal",
                error_message="no tickers in document",
                latency_ms=(perf_counter() - t0) * 1000,
            )

        side_raw = user.get("side") or resolved.get("side")
        conviction_raw = user.get("conviction") or resolved.get("conviction")
        timeframe = user.get("timeframe") or resolved.get("timeframe")
        note = user.get("note") or resolved.get("note")

        side = SignalSide.coerce(side_raw)
        # ManualMetadata.conviction is 1..5; keep as-is for Signal.conviction.
        try:
            conviction = float(conviction_raw) if conviction_raw is not None else 1.0
        except (TypeError, ValueError):
            conviction = 1.0

        horizon = _timeframe_to_horizon(timeframe)
        author_id = document.get("author_id")
        author_trust = _author_trust(author_id)
        # Prefer learned channel weight if calibration has populated one;
        # fall back to hard-coded default.
        try:
            from macro_positioning.learning.signal_calibration import (
                load_channel_trust_weight,
            )
            learned = load_channel_trust_weight(channel)
        except Exception:
            learned = None
        source_trust = learned if learned is not None else _CHANNEL_TRUST.get(channel, 1.0)

        # Catalyst classification by channel
        catalyst_map = {
            "gov_insider": SignalCatalystType.POLITICAL,
            "corp_insider": SignalCatalystType.FLOW,
            "large_holder": SignalCatalystType.FLOW,
            "fed_spend": SignalCatalystType.POLITICAL,
            "lobbying": SignalCatalystType.POLITICAL,
            "social": SignalCatalystType.FLOW,
        }
        catalyst_type = catalyst_map.get(channel, SignalCatalystType.OTHER)

        # Recover the original source_slug — for funneled insider docs the
        # documents.source_id is `manual:<author_id>`, but we can use the
        # channel as the canonical source_slug for signal attribution.
        source_id = document.get("source_id", "") or ""
        if source_id.startswith("manual:"):
            source_slug = channel
        elif ":" in source_id:
            source_slug = source_id.split(":", 1)[0]
        else:
            source_slug = source_id or channel

        raw_excerpt = (document.get("raw_text") or document.get("cleaned_text") or "")[:500]
        thesis_summary = note or (document.get("title") or None)
        published = document.get("published_at")

        signals: list[Signal] = []
        for ticker in all_tickers:
            signal = Signal(
                document_id=doc_id,
                extraction_run_id=run_id,
                asset_ticker=ticker,
                asset_class="equity",      # default — insider channels are equity-heavy
                side=side,
                conviction=conviction,
                conviction_raw=str(conviction_raw) if conviction_raw is not None else None,
                horizon=horizon,
                thesis_summary=thesis_summary,
                catalyst_type=catalyst_type,
                catalyst_date=published,
                source_slug=source_slug,
                source_channel=channel,
                author_id=author_id,
                author_trust_weight=author_trust,
                source_trust_weight=source_trust,
                extractor_name=self.name,
                extractor_version=self.version,
                extractor_confidence=1.0,       # rule-based: deterministic
                model_provider="rule",
                model_name="insider_extractor",
                raw_excerpt=raw_excerpt,
                latency_ms=(perf_counter() - t0) * 1000,
            )
            signals.append(signal)

        return ExtractionResult(
            document_id=doc_id,
            extractor_name=self.name,
            extractor_version=self.version,
            status="success",
            signals=signals,
            latency_ms=(perf_counter() - t0) * 1000,
        )

"""LLM-based signal extractor for prose documents.

Routes through `brain.backends.generate()` so it inherits the existing
multi-backend fallback chain (Gemini primary → Anthropic → Ollama). The
prompt is engineered to return a strict JSON shape that maps onto the
Signal pydantic model.

Audit: every call writes a row to `agent_call_log` for cost/quality
analysis. The `extraction_call_id` on each Signal links back to that row.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Optional

from macro_positioning.brain.backends import BackendUnavailable, generate
from macro_positioning.core.settings import settings
from macro_positioning.signals.base import (
    ExtractionResult,
    Signal,
    SignalCatalystType,
    SignalHorizon,
    SignalSide,
)

log = logging.getLogger(__name__)


_SYSTEM_PROMPT = """You are a positioning-signal extractor for a discretionary macro trader.

Read the document and extract any directional positioning signals it contains.
A "positioning signal" is anything that implies a directional view on a tradeable
instrument: a trade idea, a strong opinion on price direction, a flow event
(insider buy, large allocation), or an explicit recommendation.

Output JSON ONLY, matching this schema:

{
  "signals": [
    {
      "asset_ticker": "AAPL",                  // REQUIRED — ticker symbol (uppercase)
      "asset_class": "equity",                  // equity|etf|crypto|fx|rates|commodity|option
      "secondary_tickers": [],                  // pairs, spreads, baskets
      "side": "LONG",                           // LONG|SHORT|HEDGE|EXIT|TRIM|ADD|WATCH|AVOID
      "conviction": 3.5,                        // 0..5 (0=very weak, 5=very high)
      "conviction_raw": "high conviction",      // verbatim text that justified the score
      "horizon": "swing",                       // intraday|swing|position|strategic (null if unspecified)
      "horizon_days": 14,                       // explicit number if given, else null
      "entry_zone_low": 180.0,                  // null if not specified
      "entry_zone_high": 182.0,
      "stop_loss": 175.0,
      "target_1": 195.0,
      "target_2": 210.0,
      "invalidation": "loses 175 on close",
      "thesis_summary": "rotation into mega-cap quality on Fed pivot",
      "thesis_tags": ["fed_pivot", "quality_rotation"],
      "macro_regime_tags": ["risk_on_expansion"],
      "catalyst_type": "macro_print",           // earnings|macro_print|political|technical|flow|corporate|other
      "catalyst_date": "2026-06-15",            // ISO date if known, else null
      "catalyst_summary": "next CPI print",
      "position_size_hint": 2.0,                // numeric size if mentioned
      "position_size_unit": "pct_equity",       // pct_equity|usd|shares|r
      "raw_excerpt": "the exact span of text this signal came from (max 300 chars)",
      "extractor_confidence": 0.85              // YOUR confidence in this extraction, 0..1
    }
  ],
  "no_signal_reason": null                       // if no signals, explain briefly
}

RULES:
  - Only extract signals the author explicitly or strongly implies. Do not
    fabricate trade ideas from incidental ticker mentions.
  - TICKERS FROM URLs DON'T COUNT. A ticker that appears ONLY inside a URL,
    exchange landing page, referral/affiliate link, or "ref="/"access code"
    promo (e.g. asterdex.com/.../BTCUSDT?ref=ABC) is NOT a signal. The
    ticker must appear in the author's own prose. If the document is just a
    promo/referral link with no genuine directional thesis in the prose,
    return signals=[] with no_signal_reason="promotional/referral link".
  - thesis_summary MUST paraphrase text actually present in DOCUMENT BODY.
    Never invent or inflate. Do NOT emit promotional boilerplate like
    "extremely high conviction profitable trading opportunity" — if the body
    doesn't justify a thesis in the author's own words, set it to null.
  - If the document is news with no directional view, return signals=[]
    and explain in no_signal_reason.
  - Multiple instruments in one thesis → emit one signal per instrument,
    cross-linking via secondary_tickers.
  - When the author rotates (e.g. "sold QQQ, bought XLE"), emit TWO
    signals: EXIT QQQ and LONG XLE.
  - CONDITIONAL / NEUTRAL commentary is WATCH, not LONG/SHORT. Map-style
    posts ("support 65k, resistance 70k"), oversold-bounce calls, and
    "if X then Y / if it fails then Z" two-sided scenarios express NO
    standing directional bias — use side="WATCH". Only use LONG/SHORT when
    the author states a clear committed direction.
  - Conviction calibration (BE STRICT — most posts are 2-3, not 4-5):
      5 = staked entire book, explicit aggressive size + levels
      4 = high-conviction sized bet WITH an explicit entry zone, target,
          stop, OR position size stated
      3 = baseline position with some rationale
      2 = tentative / exploratory / conditional
      1 = just watching
    Conviction >= 4 REQUIRES at least one concrete commitment detail
    (entry_zone, target, stop, or position_size). Hype phrases alone
    ("free money", "insanely bullish", "easy money", "to the moon") with
    NO levels or size are conviction 2 at most — do not let adjectives
    drive the score.
  - Use null (not empty string) for unknown fields.
  - Output VALID JSON. No prose, no markdown fences, no commentary.
"""


def _build_user_prompt(document: dict) -> str:
    """Compose the document context the model sees."""
    parts = [
        f"DOCUMENT_ID: {document.get('document_id')}",
        f"SOURCE: {document.get('source_id')}",
        f"AUTHOR: {document.get('author') or 'unknown'}",
        f"PUBLISHED_AT: {document.get('published_at')}",
        f"TITLE: {document.get('title') or '(none)'}",
    ]

    # Pre-extracted hint tags from tags_json (e.g. tickers already detected)
    tags_json = document.get("tags_json")
    if tags_json:
        try:
            tags = json.loads(tags_json)
            hint_tickers = tags.get("tickers") or []
            if hint_tickers:
                parts.append(f"PRE_DETECTED_TICKERS: {', '.join(hint_tickers)}")
        except (TypeError, ValueError):
            pass

    # User-supplied metadata (if a manual drop with explicit side/conviction)
    meta_json = document.get("user_metadata_json")
    if meta_json:
        try:
            meta = json.loads(meta_json)
            user = meta.get("user") or {}
            if any(user.values()):
                parts.append(f"USER_METADATA: {json.dumps(user)}")
        except (TypeError, ValueError):
            pass

    body = document.get("cleaned_text") or document.get("raw_text") or ""
    # Cap body to keep prompts cheap — most signals are in the first
    # paragraph or two.
    if len(body) > 6000:
        body = body[:6000] + "\n[...truncated]"
    parts.append("")
    parts.append("DOCUMENT BODY:")
    parts.append(body)

    return "\n".join(parts)


def _parse_json_response(text: str) -> dict:
    """Best-effort JSON parse — strips markdown fences if present."""
    t = text.strip()
    if t.startswith("```"):
        # Strip any ```json fence
        t = t.split("\n", 1)[1] if "\n" in t else t
        if t.endswith("```"):
            t = t[:-3]
        t = t.strip()
    return json.loads(t)


def _log_agent_call(
    *,
    call_id: str,
    document_id: str,
    backend: str,
    model: str,
    prompt: str,
    output: str,
    latency_ms: float,
    success: bool,
    error: Optional[str] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    cost_usd: Optional[float] = None,
) -> None:
    """Audit row in agent_call_log for cost/quality analysis."""
    try:
        with sqlite3.connect(settings.sqlite_path) as conn:
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute(
                """
                INSERT INTO agent_call_log (
                    call_id, agent_name, called_at,
                    model_provider, model_name, prompt_version,
                    input_payload_json, output_payload_json,
                    latency_ms, input_tokens, output_tokens,
                    estimated_cost_usd, success, error_message, call_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    call_id,
                    "signal_llm_extractor",
                    datetime.now(UTC).isoformat(),
                    backend,
                    model,
                    "v2",
                    json.dumps({"document_id": document_id, "prompt_chars": len(prompt)}),
                    output[:8000] if output else "",
                    latency_ms,
                    input_tokens,
                    output_tokens,
                    cost_usd,
                    1 if success else 0,
                    error,
                    "llm",
                ),
            )
            conn.commit()
    except Exception:
        log.exception("Failed to write agent_call_log row")


def _coerce_signal_dict(
    raw: dict,
    *,
    document: dict,
    call_id: str,
    backend: str,
    model: str,
    run_id: Optional[str],
) -> Optional[Signal]:
    """Map a raw JSON signal dict into a validated Signal.

    Returns None if a required field is missing — the runner counts these
    as parse failures rather than killing the whole doc.
    """
    ticker = raw.get("asset_ticker")
    if not ticker:
        return None

    try:
        horizon = SignalHorizon(raw["horizon"]) if raw.get("horizon") else None
    except ValueError:
        horizon = None
    if horizon is None and raw.get("horizon_days") is not None:
        try:
            horizon = SignalHorizon.from_days(int(raw["horizon_days"]))
        except (TypeError, ValueError):
            pass

    try:
        catalyst = (
            SignalCatalystType(raw["catalyst_type"])
            if raw.get("catalyst_type") else None
        )
    except ValueError:
        catalyst = SignalCatalystType.OTHER

    try:
        return Signal(
            document_id=document["document_id"],
            extraction_run_id=run_id,
            asset_ticker=ticker,
            asset_class=raw.get("asset_class"),
            secondary_tickers=raw.get("secondary_tickers") or [],
            instrument_detail=raw.get("instrument_detail") or {},
            side=SignalSide.coerce(raw.get("side")),
            conviction=float(raw.get("conviction") or 1.0),
            conviction_raw=raw.get("conviction_raw"),
            position_size_hint=raw.get("position_size_hint"),
            position_size_unit=raw.get("position_size_unit"),
            horizon=horizon,
            horizon_days=raw.get("horizon_days"),
            entry_zone_low=raw.get("entry_zone_low"),
            entry_zone_high=raw.get("entry_zone_high"),
            stop_loss=raw.get("stop_loss"),
            target_1=raw.get("target_1"),
            target_2=raw.get("target_2"),
            invalidation=raw.get("invalidation"),
            thesis_summary=raw.get("thesis_summary"),
            thesis_tags=raw.get("thesis_tags") or [],
            macro_regime_tags=raw.get("macro_regime_tags") or [],
            catalyst_type=catalyst,
            catalyst_date=raw.get("catalyst_date"),
            catalyst_summary=raw.get("catalyst_summary"),
            source_slug=_source_slug_for(document),
            source_channel=_channel_for(document),
            author_id=document.get("author_id"),
            extractor_name="llm_extractor",
            extractor_version="v2",
            extractor_confidence=raw.get("extractor_confidence"),
            model_provider=backend,
            model_name=model,
            raw_excerpt=(raw.get("raw_excerpt") or "")[:500] or None,
            extraction_call_id=call_id,
        )
    except Exception as exc:
        log.warning("Failed to coerce signal dict %s: %s", raw, exc)
        return None


def _source_slug_for(document: dict) -> str:
    source_id = document.get("source_id", "") or ""
    if ":" in source_id:
        return source_id.split(":", 1)[0]
    return source_id or "unknown"


def _channel_for(document: dict) -> Optional[str]:
    meta_json = document.get("user_metadata_json")
    if not meta_json:
        return None
    try:
        meta = json.loads(meta_json)
        return meta.get("channel")
    except (TypeError, ValueError):
        return None


class LLMExtractor:
    """LLM signal extractor — Gemini primary, falls back per brain config."""

    name = "llm_extractor"
    version = "v2"

    def applies_to(self, document: dict) -> bool:
        # LLM extractor is the default — anything not insider-structured.
        from macro_positioning.signals.router import is_structured_insider
        return not is_structured_insider(document)

    def extract(
        self,
        document: dict,
        *,
        run_id: Optional[str] = None,
    ) -> ExtractionResult:
        t0 = perf_counter()
        doc_id = document["document_id"]
        call_id = uuid.uuid4().hex

        body = document.get("cleaned_text") or document.get("raw_text") or ""
        if not body.strip():
            return ExtractionResult(
                document_id=doc_id,
                extractor_name=self.name,
                extractor_version=self.version,
                status="no_signal",
                error_message="empty document body",
                latency_ms=(perf_counter() - t0) * 1000,
            )

        user_prompt = _build_user_prompt(document)
        backend = settings.brain_primary_backend or "gemini"

        try:
            result = generate(
                backend,
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.2,
                json_mode=True,
            )
        except BackendUnavailable as exc:
            _log_agent_call(
                call_id=call_id, document_id=doc_id, backend=backend, model="-",
                prompt=user_prompt, output="", latency_ms=0.0,
                success=False, error=str(exc),
            )
            return ExtractionResult(
                document_id=doc_id,
                extractor_name=self.name,
                extractor_version=self.version,
                status="error",
                error_message=f"backend unavailable: {exc}",
                latency_ms=(perf_counter() - t0) * 1000,
            )
        except Exception as exc:
            _log_agent_call(
                call_id=call_id, document_id=doc_id, backend=backend, model="-",
                prompt=user_prompt, output="", latency_ms=0.0,
                success=False, error=str(exc),
            )
            return ExtractionResult(
                document_id=doc_id,
                extractor_name=self.name,
                extractor_version=self.version,
                status="error",
                error_message=f"{type(exc).__name__}: {exc}",
                latency_ms=(perf_counter() - t0) * 1000,
            )

        _log_agent_call(
            call_id=call_id, document_id=doc_id,
            backend=backend, model=result.model,
            prompt=user_prompt, output=result.text,
            latency_ms=result.latency_ms, success=True,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost_usd=result.cost_usd,
        )

        try:
            parsed = _parse_json_response(result.text)
        except json.JSONDecodeError as exc:
            return ExtractionResult(
                document_id=doc_id,
                extractor_name=self.name,
                extractor_version=self.version,
                status="error",
                error_message=f"JSON parse failure: {exc}",
                latency_ms=result.latency_ms,
            )

        raw_signals = parsed.get("signals") or []
        if not raw_signals:
            return ExtractionResult(
                document_id=doc_id,
                extractor_name=self.name,
                extractor_version=self.version,
                status="no_signal",
                error_message=parsed.get("no_signal_reason"),
                latency_ms=result.latency_ms,
            )

        signals: list[Signal] = []
        for raw in raw_signals:
            s = _coerce_signal_dict(
                raw, document=document, call_id=call_id,
                backend=backend, model=result.model, run_id=run_id,
            )
            if s is not None:
                # Attach latency + cost to each signal so the audit trail
                # is per-row. Tokens are shared across all signals from
                # one extraction call — we report them once on the first
                # signal and leave the rest at None, since splitting
                # tokens-per-signal would be misleading.
                s.latency_ms = result.latency_ms
                if not signals:  # first signal carries the headline cost
                    s.input_tokens = result.input_tokens
                    s.output_tokens = result.output_tokens
                    s.cost_usd = result.cost_usd
                signals.append(s)

        return ExtractionResult(
            document_id=doc_id,
            extractor_name=self.name,
            extractor_version=self.version,
            status="success" if signals else "no_signal",
            signals=signals,
            latency_ms=result.latency_ms,
        )

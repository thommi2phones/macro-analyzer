"""Vision-based signal extractor for chart screenshots.

For manual drops with image attachments: hash → check `vision_cache` →
miss calls `brain.vision.analyze_chart_file()` → maps the chart read
into a Signal.

Division of labour with the LLM extractor:
  - `llm_extractor` reads the prose body → side / horizon / catalyst /
    thesis. It's text-blind to the chart.
  - `vision_extractor` reads the chart pixels → entry zone, stop, target,
    technical setup type, trend strength. It does NOT override direction
    from user metadata or prose — if the chart is "bullish" but the user
    typed SHORT, we trust the user.

Both run on the same chart doc (router fan-out) and produce two Signal
rows that the composer aggregates per ticker. This keeps the
extraction-time provenance honest: levels came from vision, thesis came
from prose, direction came from the user.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Optional

from macro_positioning.brain.backends import load_image_bytes
from macro_positioning.brain.vision import analyze_chart_file
from macro_positioning.core.settings import settings
from macro_positioning.signals.base import (
    ExtractionResult,
    Signal,
    SignalCatalystType,
    SignalHorizon,
    SignalSide,
)

log = logging.getLogger(__name__)


def _to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        # Some chart-vision outputs return prices as strings with $ etc.
        if isinstance(v, str):
            cleaned = v.replace("$", "").replace(",", "").strip()
            try:
                return float(cleaned)
            except ValueError:
                return None
        return None


def _extract_levels(chart_read: dict) -> dict:
    """Pull support/resistance arrays from the chart-vision response.

    Tolerant of variations in shape (list of floats, list of strings,
    list of dicts with `price` key). Returns canonical {support, resistance}
    each as a sorted list of floats.
    """
    levels = chart_read.get("key_levels") or {}

    def _flatten(items) -> list[float]:
        out: list[float] = []
        for x in items or []:
            if isinstance(x, dict):
                v = _to_float(x.get("price") or x.get("level") or x.get("value"))
            else:
                v = _to_float(x)
            if v is not None:
                out.append(v)
        return sorted(out)

    return {
        "support": _flatten(levels.get("support")),
        "resistance": _flatten(levels.get("resistance")),
    }


def _hash_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _vision_cache_get(image_hash: str, *, db_path: Path) -> Optional[dict]:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT result_json, model FROM vision_cache WHERE image_sha256 = ?",
            (image_hash,),
        ).fetchone()
    if not row:
        return None
    try:
        result = json.loads(row[0])
        result["_cached"] = True
        result["_model"] = row[1]
        return result
    except (TypeError, ValueError):
        return None


def _vision_cache_put(
    image_hash: str, *, model: str, result: dict, latency_ms: float, db_path: Path
) -> None:
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute(
                """
                INSERT OR REPLACE INTO vision_cache
                    (image_sha256, model, result_json, latency_ms, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    image_hash,
                    model,
                    json.dumps(result),
                    latency_ms,
                    datetime.now(UTC).isoformat(),
                ),
            )
            conn.commit()
    except Exception:
        log.exception("vision_cache write failed for %s", image_hash[:12])


def _attachment_paths(document: dict) -> list[str]:
    raw = document.get("attachment_paths_json")
    if raw:
        try:
            return list(json.loads(raw))
        except (TypeError, ValueError):
            pass
    single = document.get("attachment_path")
    return [single] if single else []


def _user_metadata(document: dict) -> dict:
    raw = document.get("user_metadata_json")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}


def _resolve_image_path(rel_or_abs: str) -> Path:
    """Storage paths can be relative to base_dir (uploads/...) or absolute."""
    p = Path(rel_or_abs)
    if p.is_absolute():
        return p
    return settings.base_dir / rel_or_abs


def _derive_levels_for_side(
    side: SignalSide, supports: list[float], resistances: list[float]
) -> dict:
    """Pick stop_loss + target_1 based on side and the chart's level stack."""
    out: dict[str, Optional[float]] = {
        "stop_loss": None,
        "target_1": None,
        "target_2": None,
    }
    if side in (SignalSide.LONG, SignalSide.ADD):
        if supports:
            out["stop_loss"] = supports[0]      # nearest support below entry
        if resistances:
            out["target_1"] = resistances[0]
            if len(resistances) > 1:
                out["target_2"] = resistances[1]
    elif side in (SignalSide.SHORT, SignalSide.HEDGE):
        if resistances:
            out["stop_loss"] = resistances[-1]  # nearest resistance above entry
        if supports:
            out["target_1"] = supports[-1]
            if len(supports) > 1:
                out["target_2"] = supports[-2]
    return out


def _confidence_from_chart(chart_read: dict) -> float:
    raw = chart_read.get("confidence")
    if raw is None:
        return 0.5
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return 0.5


def _has_attachments(document: dict) -> bool:
    return bool(_attachment_paths(document))


class VisionExtractor:
    """Chart-screenshot signal extractor (Gemini/Claude multimodal)."""

    name = "vision_extractor"
    version = "v1"

    def applies_to(self, document: dict) -> bool:
        return _has_attachments(document)

    def extract(
        self,
        document: dict,
        *,
        run_id: Optional[str] = None,
    ) -> ExtractionResult:
        t0 = perf_counter()
        doc_id = document["document_id"]
        attachments = _attachment_paths(document)
        if not attachments:
            return ExtractionResult(
                document_id=doc_id,
                extractor_name=self.name,
                extractor_version=self.version,
                status="skipped",
                error_message="no attachments",
                latency_ms=(perf_counter() - t0) * 1000,
            )

        meta = _user_metadata(document)
        user = meta.get("user") or {}
        resolved = meta.get("resolved") or {}
        channel = meta.get("channel")

        user_ticker = (user.get("ticker") or resolved.get("ticker") or "").upper() or None
        user_side = SignalSide.coerce(user.get("side") or resolved.get("side"))
        try:
            user_conv = float(user.get("conviction") or resolved.get("conviction") or 2.5)
        except (TypeError, ValueError):
            user_conv = 2.5
        timeframe = user.get("timeframe") or resolved.get("timeframe")

        # Provenance
        source_id = document.get("source_id", "") or ""
        source_slug = source_id.split(":", 1)[0] if ":" in source_id else (source_id or "unknown")

        db_path = settings.sqlite_path
        backend = settings.brain_vision_backend or "gemini"
        signals: list[Signal] = []
        cache_hits = 0
        call_errors: list[str] = []

        for idx, rel in enumerate(attachments):
            try:
                abs_path = _resolve_image_path(rel)
                if not abs_path.exists():
                    call_errors.append(f"image not found: {rel}")
                    continue

                # Hash for cache lookup. We always read bytes (cheap, local).
                image_bytes, _mime = load_image_bytes(abs_path)
                image_hash = _hash_bytes(image_bytes)

                cached = _vision_cache_get(image_hash, db_path=db_path)
                if cached:
                    chart_read = cached
                    model_name = cached.get("_model") or "cached"
                    latency = 0.0
                    cache_hits += 1
                else:
                    asset_context_bits = []
                    if user_ticker:
                        asset_context_bits.append(f"Ticker: {user_ticker}")
                    if timeframe:
                        asset_context_bits.append(f"Timeframe: {timeframe}")
                    if user_side != SignalSide.WATCH:
                        asset_context_bits.append(f"User bias: {user_side.value}")
                    asset_context = " · ".join(asset_context_bits)

                    t_call = perf_counter()
                    chart_read = analyze_chart_file(
                        file_path=str(abs_path),
                        asset_context=asset_context,
                        additional_context=(document.get("title") or ""),
                        backend=backend,
                    )
                    latency = (perf_counter() - t_call) * 1000
                    if "error" in chart_read:
                        call_errors.append(
                            f"vision error on {Path(rel).name}: {chart_read['error']}"
                        )
                        continue
                    model_name = chart_read.get("_model") or backend
                    _vision_cache_put(
                        image_hash,
                        model=model_name,
                        result=chart_read,
                        latency_ms=latency,
                        db_path=db_path,
                    )

                # Resolve ticker: user metadata wins; otherwise the chart's
                # asset field (best-effort, often "BTCUSD" or "$NVDA").
                ticker = user_ticker
                if not ticker:
                    asset = chart_read.get("asset") or ""
                    # Strip common decorations
                    ticker = asset.replace("$", "").split()[0].upper() if asset else None
                if not ticker:
                    call_errors.append(f"{Path(rel).name}: no ticker resolvable")
                    continue

                levels = _extract_levels(chart_read)
                resolved_levels = _derive_levels_for_side(
                    user_side, levels["support"], levels["resistance"]
                )

                # Map timeframe → horizon. Chart timeframe and user
                # timeframe usually agree; prefer the user's.
                tf_for_horizon = (timeframe or chart_read.get("timeframe") or "").upper()
                horizon = None
                if tf_for_horizon in ("1H", "4H"):
                    horizon = SignalHorizon.INTRADAY
                elif tf_for_horizon == "1D":
                    horizon = SignalHorizon.SWING
                elif tf_for_horizon == "1W":
                    horizon = SignalHorizon.POSITION

                # Trend strength as a conviction modifier. Strong + user
                # bias agrees = small boost; weak / mixed = small cut.
                strength = (chart_read.get("trend_strength") or "").lower()
                trend = (chart_read.get("trend_direction") or "").lower()
                conv = user_conv
                bullish_chart = trend in ("bullish",)
                bearish_chart = trend in ("bearish",)
                if user_side in (SignalSide.LONG, SignalSide.ADD) and bullish_chart and strength == "strong":
                    conv = min(5.0, conv + 0.5)
                elif user_side in (SignalSide.SHORT, SignalSide.HEDGE) and bearish_chart and strength == "strong":
                    conv = min(5.0, conv + 0.5)
                elif user_side in (SignalSide.LONG,) and bearish_chart:
                    conv = max(0.5, conv - 0.5)
                elif user_side in (SignalSide.SHORT,) and bullish_chart:
                    conv = max(0.5, conv - 0.5)

                patterns = chart_read.get("patterns") or []
                summary = chart_read.get("summary") or chart_read.get(
                    "positioning_implications"
                )
                if isinstance(summary, list):
                    summary = " · ".join(str(s) for s in summary)

                signal = Signal(
                    document_id=doc_id,
                    extraction_run_id=run_id,
                    asset_ticker=ticker,
                    asset_class="equity",
                    side=user_side,
                    conviction=conv,
                    conviction_raw=f"vision-confidence={chart_read.get('confidence')}",
                    horizon=horizon,
                    entry_zone_low=None,            # vision doesn't pin entries reliably
                    entry_zone_high=None,
                    stop_loss=resolved_levels["stop_loss"],
                    target_1=resolved_levels["target_1"],
                    target_2=resolved_levels["target_2"],
                    invalidation=summary if isinstance(summary, str) else None,
                    thesis_summary=summary if isinstance(summary, str) else None,
                    thesis_tags=[p for p in patterns if isinstance(p, str)],
                    catalyst_type=SignalCatalystType.TECHNICAL,
                    source_slug=source_slug,
                    source_channel=channel,
                    author_id=document.get("author_id"),
                    extractor_name=self.name,
                    extractor_version=self.version,
                    extractor_confidence=_confidence_from_chart(chart_read),
                    model_provider=backend,
                    model_name=model_name,
                    raw_excerpt=f"chart_{idx+1}: {Path(rel).name}",
                    instrument_detail={
                        "chart_timeframe": chart_read.get("timeframe"),
                        "chart_trend": trend or None,
                        "chart_strength": strength or None,
                        "chart_volume_signal": chart_read.get("volume_signal"),
                        "chart_patterns": patterns,
                        "attachment_index": idx,
                        "attachment_path": rel,
                        "vision_cached": bool(cached),
                    },
                    latency_ms=latency,
                )
                signals.append(signal)
            except Exception as exc:
                log.exception("vision_extractor failed on %s", rel)
                call_errors.append(f"{Path(rel).name}: {type(exc).__name__}: {exc}")

        elapsed = (perf_counter() - t0) * 1000
        if not signals:
            return ExtractionResult(
                document_id=doc_id,
                extractor_name=self.name,
                extractor_version=self.version,
                status="no_signal" if not call_errors else "error",
                error_message="; ".join(call_errors) if call_errors else None,
                latency_ms=elapsed,
            )

        return ExtractionResult(
            document_id=doc_id,
            extractor_name=self.name,
            extractor_version=self.version,
            status="success",
            signals=signals,
            error_message="; ".join(call_errors) if call_errors else None,
            latency_ms=elapsed,
        )

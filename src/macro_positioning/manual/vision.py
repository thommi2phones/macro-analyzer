"""Chart vision for manual /inbox drops — Claude Sonnet by default.

Flow:
  1. Compute sha256 of the raw image bytes.
  2. If `vision_cache` already has a row for that hash, return it. Free.
  3. Else: downscale the image if wider than `vision_max_image_width`,
     send via `generate_anthropic` with the framework prompt cached
     server-side (90% off on cached prompt tokens), parse JSON, cache.
  4. Log the call per `docs/logging_contract.md`.

Model is configurable via `settings.vision_model` — Sonnet 4.6 by default
(~5x cheaper than Opus, near-identical chart quality). Override per call
for high-conviction reprocessing.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from macro_positioning.brain.backends import BackendUnavailable, generate_anthropic
from macro_positioning.brain.observability import log_brain_call
from macro_positioning.core.settings import settings
from macro_positioning.manual.models import TradeRecord


logger = logging.getLogger(__name__)


PROMPT_PATH = Path("config/manual_chart_framework.md")

# Anthropic accepts at most 5 image messages with hard size limits; chart
# screenshots compress well to ~1024px wide at JPEG 85 quality without
# losing the price labels / indicator text Claude needs to extract levels.


# ── Image preprocessing ──────────────────────────────────────────────────────


def _resize_if_large(image_bytes: bytes, mime: str) -> tuple[bytes, str]:
    """Downscale wide images to `vision_resize_target_width` keeping aspect
    ratio. No-op if width <= `vision_max_image_width` or if Pillow isn't
    installed (which would only happen on a broken venv — Pillow is a
    declared dep). Returns (bytes, mime) — JPEG output to save tokens.
    """
    try:
        from PIL import Image  # type: ignore
    except Exception as e:  # pragma: no cover
        logger.warning("PIL unavailable, skipping resize: %s", e)
        return image_bytes, mime

    max_w = settings.vision_max_image_width
    target_w = settings.vision_resize_target_width
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            if img.width <= max_w:
                return image_bytes, mime
            ratio = target_w / float(img.width)
            new_h = max(1, int(img.height * ratio))
            resized = img.resize((target_w, new_h), Image.LANCZOS)
            if resized.mode in ("RGBA", "P"):
                resized = resized.convert("RGB")
            buf = io.BytesIO()
            resized.save(buf, format="JPEG", quality=85, optimize=True)
            return buf.getvalue(), "image/jpeg"
    except Exception as e:
        logger.warning("resize failed, sending original: %s", e)
        return image_bytes, mime


# ── Cache (hash-dedupe) ──────────────────────────────────────────────────────


def _cache_lookup(image_sha256: str, model: str) -> Optional[dict]:
    if not settings.vision_cache_enabled:
        return None
    try:
        with sqlite3.connect(settings.sqlite_path) as c:
            row = c.execute(
                "SELECT result_json FROM vision_cache WHERE image_sha256=? AND model=?",
                (image_sha256, model),
            ).fetchone()
    except sqlite3.OperationalError:
        return None  # table may not exist yet on a stale DB
    if not row:
        return None
    try:
        return json.loads(row[0])
    except json.JSONDecodeError:
        return None


def _cache_store(image_sha256: str, model: str, result: dict, latency_ms: float) -> None:
    if not settings.vision_cache_enabled:
        return
    try:
        with sqlite3.connect(settings.sqlite_path) as c:
            c.execute("PRAGMA busy_timeout=5000")
            c.execute(
                "INSERT OR REPLACE INTO vision_cache "
                "(image_sha256, model, result_json, latency_ms, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (image_sha256, model, json.dumps(result), latency_ms,
                 datetime.now(UTC).isoformat()),
            )
            c.commit()
    except sqlite3.OperationalError as e:
        logger.warning("vision_cache write failed: %s", e)


# ── Prompt + response handling ───────────────────────────────────────────────


_PROMPT_CACHE: Optional[str] = None


def _load_prompt() -> str:
    """Read the chart framework prompt once per process."""
    global _PROMPT_CACHE
    if _PROMPT_CACHE is None:
        path = settings.base_dir / PROMPT_PATH if not PROMPT_PATH.is_absolute() else PROMPT_PATH
        if not path.exists():
            # Worktree fallback: prompt lives at the repo root.
            path = Path(__file__).resolve().parents[3] / PROMPT_PATH
        _PROMPT_CACHE = path.read_text(encoding="utf-8")
    return _PROMPT_CACHE


def _parse_response(text: str) -> dict:
    """Strip Markdown fencing and json-parse Claude's reply."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
    if t.endswith("```"):
        t = t[:-3]
    return json.loads(t.strip())


# ── Public API ───────────────────────────────────────────────────────────────


def analyze_manual_chart(
    image_path: str | Path,
    *,
    model: Optional[str] = None,
    asset_context: str = "",
) -> dict:
    """Analyze a chart screenshot, returning TradeRecord-shaped dict.

    Returns the raw dict (not a Pydantic instance) because callers want to
    JSON-serialize it directly into `documents.extracted_features_json`.
    On error returns `{"error": "..."}` so the drainer can mark the row
    failed without raising.
    """
    p = Path(image_path)
    if not p.is_absolute():
        p = (settings.base_dir / image_path).resolve()
    if not p.exists():
        return {"error": f"image not found: {p}"}

    raw_bytes = p.read_bytes()
    image_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    target_model = model or settings.vision_model

    cached = _cache_lookup(image_sha256, target_model)
    if cached is not None:
        logger.info("vision cache hit for %s (%s)", p.name, target_model)
        return {**cached, "cache_hit": True}

    if not settings.anthropic_api_key:
        return {"error": "MPA_ANTHROPIC_API_KEY not configured"}

    ext = p.suffix.lower().lstrip(".") or "png"
    mime_in = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"
    image_bytes, mime = _resize_if_large(raw_bytes, mime_in)

    system_prompt = _load_prompt()
    user_prompt = (
        "Analyze this chart screenshot and respond with valid JSON ONLY "
        "(no prose, no Markdown fences). The JSON must conform to the "
        "TradeRecord schema described above."
    )
    if asset_context:
        user_prompt += f"\n\nAsset context: {asset_context}"

    t0 = time.time()
    try:
        result = generate_anthropic(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=target_model,
            image_data=image_bytes,
            image_mime=mime,
            temperature=0.2,
            max_tokens=4096,
        )
    except BackendUnavailable as e:
        return {"error": str(e)}
    except Exception as e:
        logger.exception("Claude vision call failed")
        log_brain_call(
            call_type="vision",
            backend="anthropic", model=target_model,
            input_size=len(image_bytes), output_size=0, latency_ms=0.0,
            success=False, error=str(e),
        )
        return {"error": str(e)}

    latency = (time.time() - t0) * 1000

    try:
        parsed = _parse_response(result.text)
    except json.JSONDecodeError as e:
        logger.warning("vision response not JSON: %s\nraw: %s", e, result.text[:500])
        log_brain_call(
            call_type="vision",
            backend="anthropic", model=target_model,
            input_size=len(image_bytes), output_size=len(result.text), latency_ms=latency,
            success=False, error=f"json_decode: {e}",
        )
        return {"error": f"non-JSON response: {e}", "raw_text": result.text[:2000]}

    # Validate against the canonical TradeRecord shape — drops keys Claude
    # may have hallucinated, fills defaults, normalizes direction/bias.
    try:
        record = TradeRecord(**parsed)
        out = record.model_dump()
    except Exception as e:
        logger.warning("TradeRecord validation failed, returning raw parsed: %s", e)
        out = parsed

    out["image_sha256"] = image_sha256
    out["analyzed_at"] = datetime.now(UTC).isoformat()
    out["vision_model"] = target_model

    log_brain_call(
        call_type="vision",
        backend="anthropic", model=target_model,
        input_size=len(image_bytes),
        output_size=len(result.text),
        latency_ms=latency,
        success=True,
    )
    _cache_store(image_sha256, target_model, out, latency)
    return out


def analyze_manual_charts(image_paths: list[str | Path], **kwargs) -> list[dict]:
    """Batch helper — analyze each image, return list of results in order."""
    return [analyze_manual_chart(p, **kwargs) for p in image_paths]

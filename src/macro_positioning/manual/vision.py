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


# Extension → media type as the Anthropic API expects it. Must match the
# actual bytes: the API sniffs the payload and 400s on a mismatch.
_MIME_BY_EXT = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
}


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
    caption: str = "",
) -> dict:
    """Analyze a chart screenshot, returning TradeRecord-shaped dict.

    `caption` is the trader's message text posted ALONGSIDE the chart. It
    frequently states the actual call — direction, target, whether the move
    already happened, or that it's conditional ("can long ON A BREAK over")
    — context the image alone can't convey. Passed into the prompt and
    folded into the cache key so the same image with a different caption
    re-analyzes.

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

    # Cache key folds in the caption — same chart, different message = a
    # different call, so it must not return a stale image-only result.
    cap = (caption or "").strip()
    cache_key = (
        hashlib.sha256(raw_bytes + b"\x00" + cap.encode("utf-8")).hexdigest()
        if cap else image_sha256
    )
    cached = _cache_lookup(cache_key, target_model)
    if cached is not None:
        logger.info("vision cache hit for %s (%s)", p.name, target_model)
        return {**cached, "cache_hit": True}

    backend = settings.vision_backend or "cli"
    ext = p.suffix.lower().lstrip(".") or "png"
    # Declare the REAL media type. Defaulting non-jpg to image/png made the
    # API reject every .webp/.gif with a 400 ("appears to be a image/webp
    # image") — and that error isn't in the drainer's transient list, so
    # those docs got permanently cleared instead of retried.
    mime_in = _MIME_BY_EXT.get(ext, "image/png")
    image_bytes, mime = _resize_if_large(raw_bytes, mime_in)

    system_prompt = _load_prompt()
    user_prompt = (
        "Analyze this chart screenshot and respond with valid JSON ONLY "
        "(no prose, no Markdown fences) matching the SECTION 10 schema. "
        "Decide `call_type` FIRST: is this a single directional call, a "
        "BIDIRECTIONAL outlook (both long+short scenarios drawn — do NOT "
        "collapse to one bias), a RETROSPECTIVE chart (the move already "
        "happened — set is_forward_looking=false), or no_trade? Then fill "
        "per-setup direction + entry/stop/take_profits/final_target. "
        "Understanding WHAT KIND of call this is matters more than the "
        "indicator detail."
    )
    if cap:
        # The paired message is the trader's OWN words about this chart —
        # it usually states the actual call and often OVERRIDES what the
        # chart geometry alone implies (e.g. caption says the move already
        # happened → retrospective; "needs a break first" → conditional;
        # "BTC vs money" musing → no_trade). Weight it heavily.
        user_prompt += (
            "\n\n=== TRADER'S MESSAGE POSTED WITH THIS CHART (weight heavily — "
            "it states the actual call and overrides chart-only guesses) ===\n"
            f"{cap[:1500]}"
        )
    if asset_context:
        user_prompt += f"\n\nAsset context: {asset_context}"

    t0 = time.time()
    text_response = None
    try:
        if backend == "cli":
            # Route through `claude -p` so we use the user's Claude Code
            # subscription (no API credits burned). The CLI's Read tool
            # accepts image paths and feeds them into the model context.
            text_response = _generate_via_cli(
                model=target_model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                image_path=p,
            )
        else:
            if not settings.anthropic_api_key:
                return {"error": "MPA_ANTHROPIC_API_KEY not configured (vision_backend=api)"}
            result = generate_anthropic(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=target_model,
                image_data=image_bytes,
                image_mime=mime,
                temperature=0.2,
                max_tokens=4096,
            )
            text_response = result.text
    except BackendUnavailable as e:
        return {"error": str(e)}
    except Exception as e:
        logger.exception("Claude vision call failed (backend=%s)", backend)
        log_brain_call(
            call_type="vision",
            backend=backend, model=target_model,
            input_size=len(image_bytes), output_size=0, latency_ms=0.0,
            success=False, error=str(e),
        )
        return {"error": str(e)}

    latency = (time.time() - t0) * 1000

    try:
        parsed = _parse_response(text_response or "")
    except json.JSONDecodeError as e:
        logger.warning("vision response not JSON: %s\nraw: %s", e, (text_response or "")[:500])
        log_brain_call(
            call_type="vision",
            backend=backend, model=target_model,
            input_size=len(image_bytes), output_size=len(text_response or ""), latency_ms=latency,
            success=False, error=f"json_decode: {e}",
        )
        return {"error": f"non-JSON response: {e}", "raw_text": (text_response or "")[:2000]}

    # Validate against the canonical TradeRecord shape — drops keys Claude
    # may have hallucinated, fills defaults, normalizes direction/bias.
    try:
        record = TradeRecord(**parsed)
        out = record.model_dump()
    except Exception as e:
        logger.warning("TradeRecord validation failed, returning raw parsed: %s", e)
        out = parsed

    # Claude sometimes returns a JSON array (multiple trade ideas on
    # one chart). Wrap it so the rest of the pipeline gets a dict and
    # the metadata fields below can be stamped on.
    if isinstance(out, list):
        out = {"trades": out, "multi_trade": True}
    elif not isinstance(out, dict):
        out = {"error": f"unexpected response type: {type(out).__name__}",
               "raw": out}

    out["image_sha256"] = image_sha256
    out["analyzed_at"] = datetime.now(UTC).isoformat()
    out["vision_model"] = target_model
    out["vision_backend"] = backend

    log_brain_call(
        call_type="vision",
        backend=backend, model=target_model,
        input_size=len(image_bytes),
        output_size=len(text_response or ""),
        latency_ms=latency,
        success=True,
    )
    _cache_store(cache_key, target_model, out, latency)
    return out


# ── CLI subprocess backend (no API credits — uses Claude Code subscription) ──


def _generate_via_cli(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    image_path: Path,
) -> str:
    """Invoke `claude -p` with the image as a Read-tool target.

    The CLI's Read tool ingests image files and feeds them to the model
    context, so Claude sees the chart without us touching the Anthropic
    API directly. Authentication flows through the user's logged-in
    Claude Code session (Pro/Max subscription) — no API key required.

    Returns the model's raw text response. Caller parses JSON.
    """
    import subprocess

    cli = settings.vision_cli_path or "claude"
    max_turns = max(2, int(settings.vision_cli_max_turns or 4))
    timeout = max(30, int(settings.vision_cli_timeout_s or 120))

    # The CLI doesn't take a system prompt arg in -p mode reliably across
    # versions, so we fold it into the user prompt with clear delimiters.
    full_prompt = (
        f'You are a chart-analysis assistant. Read the image at "{image_path}" '
        f'using the Read tool, then return ONLY a JSON object — no prose, '
        f'no Markdown fences, no commentary before or after.\n\n'
        f'=== analysis framework ===\n{system_prompt}\n\n'
        f'=== request ===\n{user_prompt}'
    )

    cmd = [
        cli, "-p",
        "--model", model,
        "--max-turns", str(max_turns),
        "--output-format", "text",
    ]
    try:
        proc = subprocess.run(
            cmd, input=full_prompt,
            capture_output=True, text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"claude CLI timeout after {timeout}s") from e
    except FileNotFoundError as e:
        raise RuntimeError(
            f"claude CLI not found on PATH (looked for '{cli}'). "
            "Set MPA_VISION_CLI_PATH or install Claude Code."
        ) from e

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"claude CLI exit {proc.returncode}: {err[:500]}")

    out = (proc.stdout or "").strip()
    if not out:
        raise RuntimeError(f"claude CLI returned empty stdout. stderr: {(proc.stderr or '')[:200]}")
    return out


def analyze_manual_charts(image_paths: list[str | Path], **kwargs) -> list[dict]:
    """Batch helper — analyze each image, return list of results in order."""
    return [analyze_manual_chart(p, **kwargs) for p in image_paths]

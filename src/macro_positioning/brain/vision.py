"""Chart / image vision — routed to any configured multimodal backend.

Default: Gemini 2.5 Pro (native multimodal). Also supports Claude via
Anthropic SDK. Direct API — no N8N dependency.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import httpx

from macro_positioning.brain.backends import generate, load_image_bytes
from macro_positioning.brain.observability import log_brain_call
from macro_positioning.brain.prompts import CHART_ANALYSIS_PROMPT
from macro_positioning.core.settings import settings

logger = logging.getLogger(__name__)


def _build_context(asset_context: str, additional_context: str) -> str:
    parts = []
    if asset_context:
        parts.append(f"Asset context: {asset_context}")
    if additional_context:
        parts.append(additional_context)
    return "\n".join(parts)


def _parse_response(text: str) -> dict:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
    if t.endswith("```"):
        t = t[:-3]
    t = t.strip()

    try:
        parsed = json.loads(t)
        parsed["analyzed_at"] = datetime.now(UTC).isoformat()
        return parsed
    except json.JSONDecodeError as e:
        logger.warning("Vision response was not JSON: %s", e)
        return {
            "raw_text": t,
            "analyzed_at": datetime.now(UTC).isoformat(),
            "parse_error": str(e),
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_chart_url(
    image_url: str,
    asset_context: str = "",
    additional_context: str = "",
    backend: str = "gemini",
) -> dict:
    """Analyze a chart from a public URL. Fetches bytes then sends to backend."""
    prompt = CHART_ANALYSIS_PROMPT.format(
        context=_build_context(asset_context, additional_context)
    )

    # Fetch image bytes — more reliable than passing URL to each backend
    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.get(image_url)
            r.raise_for_status()
            image_bytes = r.content
            # Infer MIME from content-type header
            mime = r.headers.get("content-type", "image/png").split(";")[0]
    except Exception as e:
        logger.error("Failed to fetch chart URL: %s", e)
        return {"error": f"Fetch failed: {e}"}

    try:
        result = generate(
            backend=backend,
            system_prompt="You are a macro technical analyst. Respond with valid JSON only.",
            user_prompt=prompt,
            image_data=image_bytes,
            image_mime=mime,
            temperature=0.2,
            max_tokens=4096,
            json_mode=True,
        )
    except Exception as e:
        logger.error("Vision backend %s failed: %s", backend, e)
        log_brain_call(
            call_type="vision",
            backend=backend, model="",
            input_size=len(image_bytes),
            output_size=0, latency_ms=0.0,
            success=False, error=str(e),
        )
        return {"error": str(e)}

    parsed = _parse_response(result.text)
    log_brain_call(
        call_type="vision",
        backend=backend, model=result.model,
        input_size=len(image_bytes),
        output_size=len(result.text),
        latency_ms=result.latency_ms,
        success="error" not in parsed,
    )
    return parsed


def analyze_chart_file(
    file_path: str | Path,
    asset_context: str = "",
    additional_context: str = "",
    backend: str = "gemini",
) -> dict:
    """Analyze a chart from a local file."""
    image_bytes, mime = load_image_bytes(file_path)

    prompt = CHART_ANALYSIS_PROMPT.format(
        context=_build_context(asset_context, additional_context)
    )

    logger.info("Chart analysis: %s (%d KB) via %s",
                Path(file_path).name, len(image_bytes) // 1024, backend)

    try:
        result = generate(
            backend=backend,
            system_prompt="You are a macro technical analyst. Respond with valid JSON only.",
            user_prompt=prompt,
            image_data=image_bytes,
            image_mime=mime,
            temperature=0.2,
            max_tokens=4096,
            json_mode=True,
        )
    except Exception as e:
        logger.error("Vision backend %s failed: %s", backend, e)
        return {"error": str(e)}

    parsed = _parse_response(result.text)
    log_brain_call(
        call_type="vision",
        backend=backend, model=result.model,
        input_size=len(image_bytes),
        output_size=len(result.text),
        latency_ms=result.latency_ms,
        success="error" not in parsed,
    )
    return parsed


def analyze_multiple_charts(charts: list[dict]) -> list[dict]:
    """Batch chart analysis. Each entry: {url or file_path, asset_context?}"""
    results = []
    for chart in charts:
        try:
            if "url" in chart:
                result = analyze_chart_url(
                    image_url=chart["url"],
                    asset_context=chart.get("asset_context", ""),
                )
            elif "file_path" in chart:
                result = analyze_chart_file(
                    file_path=chart["file_path"],
                    asset_context=chart.get("asset_context", ""),
                )
            else:
                continue
            results.append(result)
        except Exception as e:
            results.append({"error": str(e), "input": chart})
    return results

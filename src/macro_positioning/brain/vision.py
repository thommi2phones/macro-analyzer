"""Chart vision — Gemini 2.5 Pro multimodal via N8N.

Sends chart screenshots (URL or local file) to Gemini for structured reads:
trend direction, key levels, patterns, momentum, positioning implications.

N8N workflow setup:
  1. Webhook — POST, path: "macro-analyzer-vision", response mode: "Respond to Webhook"
  2. Google Gemini — image/analyze operation
     - Model: gemini-2.5-pro
     - Text: {{ $json.body.prompt }}
     - Input type: url
     - Image URLs: {{ $json.body.image_url }}
     - Max output tokens: 4096
  3. Respond to Webhook — first incoming item
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import httpx

from macro_positioning.brain.prompts import CHART_ANALYSIS_PROMPT
from macro_positioning.core.settings import settings

logger = logging.getLogger(__name__)


def _build_context(asset_context: str, additional_context: str) -> str:
    parts = []
    if asset_context:
        parts.append(f"Asset context: {asset_context}")
    if additional_context:
        parts.append(additional_context)
    return "\n".join(parts) if parts else ""


def _call_vision(prompt: str, image_payload: str, timeout: float = 90.0) -> dict:
    """POST to N8N vision webhook and return parsed response."""
    webhook_url = settings.n8n_vision_webhook_url
    if not webhook_url:
        raise RuntimeError(
            "N8N vision webhook not configured. Set MPA_N8N_VISION_WEBHOOK_URL in .env."
        )

    payload = {"prompt": prompt, "image_url": image_payload}

    logger.info("Chart vision request → N8N")

    with httpx.Client(timeout=timeout) as client:
        response = client.post(webhook_url, json=payload)
        response.raise_for_status()

    return _parse_response(response.json())


def _parse_response(data) -> dict:
    if isinstance(data, str):
        text = data
    elif isinstance(data, dict):
        text = data.get("text") or data.get("output") or data.get("content", "")
        if not text:
            return data
    else:
        return {"raw": str(data)}

    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        parsed = json.loads(text)
        parsed["analyzed_at"] = datetime.now(UTC).isoformat()
        return parsed
    except json.JSONDecodeError as e:
        logger.warning("Chart vision returned non-JSON: %s", e)
        return {
            "raw_text": text,
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
) -> dict:
    """Analyze a chart accessible at a public URL."""
    prompt = CHART_ANALYSIS_PROMPT.format(
        context=_build_context(asset_context, additional_context)
    )
    return _call_vision(prompt, image_url)


def analyze_chart_file(
    file_path: str | Path,
    asset_context: str = "",
    additional_context: str = "",
) -> dict:
    """Analyze a chart from a local file (base64-encoded into data URI)."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Chart file not found: {path}")

    image_bytes = path.read_bytes()
    b64 = base64.b64encode(image_bytes).decode("utf-8")

    ext = path.suffix.lower()
    mime_map = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp",
    }
    mime = mime_map.get(ext, "image/png")
    data_uri = f"data:{mime};base64,{b64}"

    prompt = CHART_ANALYSIS_PROMPT.format(
        context=_build_context(asset_context, additional_context)
    )

    logger.info("Chart file analysis: %s (%d KB)", path.name, len(image_bytes) // 1024)
    return _call_vision(prompt, data_uri, timeout=120.0)


def analyze_multiple_charts(charts: list[dict]) -> list[dict]:
    """Analyze a batch of charts. Each entry: {url or file_path, asset_context?}"""
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
                logger.warning("Chart missing 'url' or 'file_path': %s", chart)
                continue
            results.append(result)
        except Exception as e:
            logger.error("Chart analysis failed %s: %s", chart, e)
            results.append({"error": str(e), "input": chart})
    return results

"""Chart / image analysis via Gemini Vision through N8N.

Sends chart screenshots or URLs to Gemini for visual macro analysis.
Returns structured reads on trend direction, patterns, key levels,
and momentum signals.

Requires an N8N workflow:
  1. Webhook node — POST, path: "macro-analyzer-vision", response mode: "Respond to Webhook"
  2. Google Gemini node — resource: image, operation: analyze
     - Model: gemini-2.5-flash
     - Text input: {{ $json.body.prompt }}
     - Input type: url
     - Image URLs: {{ $json.body.image_url }}
     - Simplify: ON
     - Options → Max output tokens: 2048
  3. Respond to Webhook node — respond with: first incoming item

Set MPA_N8N_VISION_WEBHOOK_URL in .env.
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import httpx

from macro_positioning.core.settings import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Vision analysis prompt
# ---------------------------------------------------------------------------

CHART_ANALYSIS_PROMPT = """\
You are a senior macro technical analyst. Analyze this chart and provide a
structured read. Be specific and actionable.

{context}

Return your analysis as JSON:
```json
{{
  "asset": "What asset/instrument is shown",
  "timeframe": "Chart timeframe if visible",
  "trend_direction": "bullish / bearish / neutral / transitioning",
  "trend_strength": "strong / moderate / weak",
  "key_levels": {{
    "support": ["list of support levels"],
    "resistance": ["list of resistance levels"]
  }},
  "patterns": ["Any chart patterns identified (head & shoulders, wedge, etc.)"],
  "momentum": "Momentum read from any visible indicators (RSI, MACD, etc.)",
  "volume_signal": "Volume analysis if visible",
  "positioning_implications": ["What this chart means for positioning"],
  "confidence": 0.75,
  "summary": "2-3 sentence plain English read of this chart"
}}
```

Respond ONLY with the JSON object.
"""


# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------

def analyze_chart_url(
    image_url: str,
    asset_context: str = "",
    additional_context: str = "",
) -> dict:
    """Analyze a chart from a URL via N8N → Gemini Vision.

    Args:
        image_url: Public URL of the chart image
        asset_context: Optional context like "S&P 500 daily" or "Gold weekly"
        additional_context: Any additional context to include in the prompt

    Returns:
        Structured analysis dict with trend, levels, patterns, positioning
    """
    webhook_url = settings.n8n_vision_webhook_url
    if not webhook_url:
        raise RuntimeError(
            "N8N vision webhook URL not configured. Set MPA_N8N_VISION_WEBHOOK_URL in .env."
        )

    context_parts = []
    if asset_context:
        context_parts.append(f"Asset context: {asset_context}")
    if additional_context:
        context_parts.append(additional_context)
    context = "\n".join(context_parts) if context_parts else ""

    prompt = CHART_ANALYSIS_PROMPT.format(context=context)

    payload = {
        "prompt": prompt,
        "image_url": image_url,
    }

    logger.info("Sending chart analysis request to N8N vision webhook for: %s", image_url)

    with httpx.Client(timeout=60.0) as client:
        response = client.post(webhook_url, json=payload)
        response.raise_for_status()

    return _parse_vision_response(response.json())


def analyze_chart_file(
    file_path: str | Path,
    asset_context: str = "",
    additional_context: str = "",
) -> dict:
    """Analyze a chart from a local file via N8N → Gemini Vision.

    Encodes the image as base64 and sends it. The N8N workflow needs to be
    configured with input type "binary" for this path, or you can use
    analyze_chart_url() with a publicly accessible URL instead.

    Args:
        file_path: Path to chart screenshot (PNG, JPG, etc.)
        asset_context: Optional context like "S&P 500 daily"
        additional_context: Any additional context

    Returns:
        Structured analysis dict
    """
    webhook_url = settings.n8n_vision_webhook_url
    if not webhook_url:
        raise RuntimeError(
            "N8N vision webhook URL not configured. Set MPA_N8N_VISION_WEBHOOK_URL in .env."
        )

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Chart file not found: {path}")

    # Read and base64 encode the image
    image_bytes = path.read_bytes()
    b64 = base64.b64encode(image_bytes).decode("utf-8")

    # Detect mime type from extension
    ext = path.suffix.lower()
    mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".gif": "image/gif", ".webp": "image/webp"}
    mime = mime_map.get(ext, "image/png")

    # Build data URI for the image
    data_uri = f"data:{mime};base64,{b64}"

    context_parts = []
    if asset_context:
        context_parts.append(f"Asset context: {asset_context}")
    if additional_context:
        context_parts.append(additional_context)
    context = "\n".join(context_parts) if context_parts else ""

    prompt = CHART_ANALYSIS_PROMPT.format(context=context)

    payload = {
        "prompt": prompt,
        "image_url": data_uri,
    }

    logger.info("Sending chart file analysis to N8N vision webhook: %s (%d KB)",
                path.name, len(image_bytes) // 1024)

    with httpx.Client(timeout=90.0) as client:
        response = client.post(webhook_url, json=payload)
        response.raise_for_status()

    return _parse_vision_response(response.json())


def analyze_multiple_charts(
    charts: list[dict],
) -> list[dict]:
    """Analyze multiple charts and return all results.

    Args:
        charts: List of dicts with keys: url or file_path, asset_context (optional)

    Returns:
        List of analysis dicts
    """
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
                logger.warning("Chart entry missing 'url' or 'file_path': %s", chart)
                continue
            results.append(result)
        except Exception as e:
            logger.error("Failed to analyze chart %s: %s", chart, e)
            results.append({"error": str(e), "input": chart})

    return results


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def _parse_vision_response(data: dict | str) -> dict:
    """Parse the Gemini vision response into a structured dict."""
    if isinstance(data, str):
        text = data
    elif isinstance(data, dict):
        text = data.get("text") or data.get("output") or data.get("content", "")
        if not text:
            return data  # Already structured, return as-is
    else:
        return {"raw": str(data)}

    # Strip markdown fences
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
        logger.warning("Could not parse vision response as JSON: %s", e)
        return {
            "raw_text": text,
            "analyzed_at": datetime.now(UTC).isoformat(),
            "parse_error": str(e),
        }

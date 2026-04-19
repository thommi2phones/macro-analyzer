"""READ-direction HTTP client for pulling tactical-executor state.

Used by the macro-side dashboard to surface tactical activity next to
macro signals. All methods return None on any failure — dashboards must
render gracefully when tactical is unreachable.

Opposite direction from `regime_watch.push_to_tactical()` which WRITES
to tactical. This client only READS.

15-second in-memory cache so dashboard auto-refresh doesn't hammer
tactical-executor.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from macro_positioning.core.settings import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Small in-memory TTL cache (shared across fetch calls within one process)
# ---------------------------------------------------------------------------

_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_TTL_SECONDS = 15.0


def _cache_get(key: str) -> Any | None:
    hit = _CACHE.get(key)
    if not hit:
        return None
    expires_at, value = hit
    if time.time() >= expires_at:
        _CACHE.pop(key, None)
        return None
    return value


def _cache_put(key: str, value: Any) -> None:
    _CACHE[key] = (time.time() + _CACHE_TTL_SECONDS, value)


def invalidate_cache() -> None:
    """Drop all cached tactical state. Mostly for tests."""
    _CACHE.clear()


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _base_url() -> str | None:
    url = settings.tactical_executor_url
    return url.rstrip("/") if url else None


def _get(path: str, timeout: float = 5.0) -> Any | None:
    """GET a JSON path from the tactical executor. Returns None on any failure."""
    base = _base_url()
    if not base:
        return None

    url = f"{base}{path}"
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as e:
        logger.warning("Tactical fetch failed %s: %s", url, e)
        return None
    except ValueError as e:  # JSON parse
        logger.warning("Tactical fetch returned non-JSON %s: %s", url, e)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_configured() -> bool:
    """True when the tactical URL is set — dashboards should gate UI on this."""
    return bool(settings.tactical_executor_url)


def fetch_latest_events(limit: int = 20) -> list[dict] | None:
    """GET /events?limit=...  — most recent normalized events.

    Returns the list of events on success, None if tactical unreachable
    or the response isn't in the expected shape.
    """
    limit = max(1, min(int(limit), 200))
    cache_key = f"events:{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = _get(f"/events?limit={limit}")
    if data is None:
        return None

    # Tactical returns { ok: true, events: [...] } or just a list — handle both
    events: list[dict] | None = None
    if isinstance(data, list):
        events = data
    elif isinstance(data, dict):
        if isinstance(data.get("events"), list):
            events = data["events"]
        elif isinstance(data.get("items"), list):
            events = data["items"]

    if events is None:
        logger.warning("Tactical /events returned unexpected shape: %r", type(data))
        return None

    _cache_put(cache_key, events)
    return events


def fetch_latest_decision(setup_id: str | None = None) -> dict | None:
    """GET /decision/latest — most recent agent_packet + decision.

    Optional setup_id narrows to a specific setup.
    """
    key = f"decision:{setup_id or 'latest'}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    path = "/decision/latest"
    if setup_id:
        path += f"?setup_id={setup_id}"
    data = _get(path)
    if data is None:
        return None
    _cache_put(key, data)
    return data


def fetch_lifecycle_latest(setup_id: str | None = None, limit: int = 50) -> dict | None:
    """GET /lifecycle/latest — setup state machine snapshot."""
    key = f"lifecycle:{setup_id or 'latest'}:{limit}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    path = f"/lifecycle/latest?limit={limit}"
    if setup_id:
        path += f"&setup_id={setup_id}"
    data = _get(path)
    if data is None:
        return None
    _cache_put(key, data)
    return data


def fetch_health() -> dict | None:
    """GET /health — quick liveness probe."""
    return _get("/health", timeout=2.0)


def fetch_tactical_snapshot() -> dict:
    """Combined snapshot used by the dashboard — events + decision + lifecycle.

    Always returns a dict (never None) so dashboard can always render.
    Missing sections are set to None.
    """
    return {
        "configured": is_configured(),
        "events": fetch_latest_events(limit=25),
        "latest_decision": fetch_latest_decision(),
        "lifecycle": fetch_lifecycle_latest(limit=25),
        "health": fetch_health(),
    }

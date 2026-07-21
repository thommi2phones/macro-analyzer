"""Shared SEC EDGAR HTTP client.

EDGAR requires a contactable User-Agent or returns 403. We honor the
10-request/second rate limit by minimum-spacing inside `get_text()`.

The client caches GET responses under `<base_dir>/cache/insiders/edgar/`
so re-runs and tests don't hammer EDGAR.

Used by sec_form4, sec_13f, sec_13d_13g — anything reaching SEC.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from pathlib import Path
from typing import Optional

from macro_positioning.core.settings import settings


log = logging.getLogger(__name__)


_UA = "macro-analyzer/0.1 (personal research; contact: thomasrlindsey@gmail.com)"
_MIN_INTERVAL_SEC = 0.11  # leaves margin under the 10rps SEC limit

_last_call_lock = threading.Lock()
_last_call_at: float = 0.0


def _cache_root() -> Path:
    d = settings.base_dir / "cache" / "insiders" / "edgar"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _throttle() -> None:
    global _last_call_at
    with _last_call_lock:
        now = time.monotonic()
        wait = _MIN_INTERVAL_SEC - (now - _last_call_at)
        if wait > 0:
            time.sleep(wait)
        _last_call_at = time.monotonic()


def _cache_path_for(url: str) -> Path:
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return _cache_root() / f"{h[:2]}" / f"{h}.bin"


def get(url: str, *, timeout: float = 30.0, use_cache: bool = True) -> bytes:
    """GET with UA + cache + throttle. Returns raw bytes."""
    cache_path = _cache_path_for(url)
    if use_cache and cache_path.exists() and cache_path.stat().st_size > 0:
        return cache_path.read_bytes()

    import httpx  # type: ignore

    _throttle()
    log.debug("EDGAR GET %s", url)
    with httpx.Client(timeout=timeout, headers={"User-Agent": _UA}, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.content

    if use_cache:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(data)
    return data


def get_text(url: str, *, timeout: float = 30.0, use_cache: bool = True) -> str:
    return get(url, timeout=timeout, use_cache=use_cache).decode("utf-8", errors="replace")

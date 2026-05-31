"""Trading-rule framework — measured discipline + (advisory) gate.

Pure-compute modules over inputs + (read-only) a sqlite3.Connection.
Caps + correlated buckets are loaded from JSON in `config/`. Each
sub-module is independently testable and side-effect-free:

  confluence — Pattern + Fib + Indicator subscores → 0..8 total + tier
  risk       — entry/stop/size → account_risk_pct; sizing validation
  portfolio  — current open-trade exposure + bucket lookup + caps check
  gate       — composes the above into a GateDecision for a TradeProposal

The gate evaluator is importable in-process (for a future native
execution layer) and HTTP-exposed via api/rules_routes.py (for the
external trading agent). Same function, two boundaries.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from macro_positioning.core.settings import settings


CAPS_PATH = "config/risk_caps.json"
BUCKETS_PATH = "config/correlation_buckets.json"


@lru_cache(maxsize=1)
def load_caps(path: str | Path | None = None) -> dict:
    """Load the declarative risk-caps JSON. Cached for the process lifetime;
    pass an explicit `path` in tests to redirect."""
    p = Path(path) if path is not None else settings.base_dir / CAPS_PATH
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_buckets(path: str | Path | None = None) -> dict:
    """Load correlation-bucket definitions. Cached; pass `path` in tests."""
    p = Path(path) if path is not None else settings.base_dir / BUCKETS_PATH
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def reset_caches() -> None:
    """Drop cached config loads. Used in tests after monkeypatching files."""
    load_caps.cache_clear()
    load_buckets.cache_clear()


__all__ = ["load_caps", "load_buckets", "reset_caches"]

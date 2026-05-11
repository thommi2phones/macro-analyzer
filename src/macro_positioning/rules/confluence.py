"""Confluence-score rubric — 0..8 with three subscores.

  Pattern    0..3  — 0 none / 1 weak / 2 textbook / 3 textbook + multi-timeframe
  Fib        0..3  — 0 none / 1 white confluence / 2 yellow / 3 green at breakout level
  Indicator  0..2  — 0 mixed-or-against / 1 partial / 2 full (MACD + RSI + Squeeze all agree)

Tier mapping (sourced from config/risk_caps.json::confluence_tiers):
  0..insufficient_max   → "insufficient"   (do not trade)
  standard_min..below_high → "standard"     (3..5% allocation)
  high_conviction_min..  → "high_conviction" (7.5..8% allocation; rare)

Pure compute. No DB, no I/O. The remap from existing TradeRecord 1..5
scores into 0..8 lives in `from_legacy_score()`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from macro_positioning.rules import load_caps


Tier = Literal["insufficient", "standard", "high_conviction"]


PATTERN_MIN, PATTERN_MAX = 0, 3
FIB_MIN, FIB_MAX = 0, 3
INDICATOR_MIN, INDICATOR_MAX = 0, 2


@dataclass(frozen=True)
class ConfluenceBreakdown:
    pattern: int
    fib: int
    indicator: int
    total: int
    tier: Tier

    def as_dict(self) -> dict:
        return {
            "pattern": self.pattern,
            "fib": self.fib,
            "indicator": self.indicator,
            "total": self.total,
            "tier": self.tier,
        }


def score_confluence(
    pattern: int,
    fib: int,
    indicator: int,
    *,
    caps_path: str | None = None,
) -> ConfluenceBreakdown:
    """Compose the three subscores into a total + tier.

    Each subscore is clamped to its declared range so callers can't
    smuggle in out-of-band values that distort downstream tier math.
    """
    p = _clamp(pattern, PATTERN_MIN, PATTERN_MAX)
    f = _clamp(fib, FIB_MIN, FIB_MAX)
    i = _clamp(indicator, INDICATOR_MIN, INDICATOR_MAX)
    total = p + f + i
    tier = tier_for_score(total, caps_path=caps_path)
    return ConfluenceBreakdown(pattern=p, fib=f, indicator=i, total=total, tier=tier)


def tier_for_score(total: int, *, caps_path: str | None = None) -> Tier:
    caps = load_caps(caps_path) if caps_path else load_caps()
    t = caps["confluence_tiers"]
    if total >= t["high_conviction_min"]:
        return "high_conviction"
    if total >= t["standard_min"]:
        return "standard"
    return "insufficient"


def from_legacy_score(legacy_1_to_5: int) -> ConfluenceBreakdown:
    """Map an existing 1..5 TradeRecord confluence score into the 0..8 space.

    Used for one-shot backfill of historical TradeRecord rows where only
    the legacy composite is known. The mapping is intentionally lossy:
    we assume a balanced split across the three components, so caller
    sees a plausible breakdown but should NOT treat the subscores as
    "what the vision actually saw" for new trades.

    Mapping:
      1 → (1,0,0) = 1, insufficient
      2 → (1,1,0) = 2, insufficient
      3 → (2,1,1) = 4, insufficient
      4 → (2,2,1) = 5, standard
      5 → (3,3,2) = 8, high_conviction
    """
    table = {
        1: (1, 0, 0),
        2: (1, 1, 0),
        3: (2, 1, 1),
        4: (2, 2, 1),
        5: (3, 3, 2),
    }
    if legacy_1_to_5 not in table:
        raise ValueError(f"legacy confluence must be 1..5, got {legacy_1_to_5!r}")
    p, f, i = table[legacy_1_to_5]
    return score_confluence(p, f, i)


def _clamp(v: int, lo: int, hi: int) -> int:
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v

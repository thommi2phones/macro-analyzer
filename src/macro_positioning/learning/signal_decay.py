"""Time-decay scoring for manual-input setups.

Direct trade setups are perishable: a Big_Nuts cup-and-handle from 3 days
ago is actionable; the same setup from 90 days ago has played out one way
or another. This module computes:

  • days_since_chart  — how old the chart is (uses published_at from the
    TradingView header, not ingested_at)
  • decay_window      — timeframe-aware window for how long a setup stays
    "live" (intraday=days, swing=weeks, position=months)
  • decay_weight      — 1.0 = fresh, 0.0 = fully decayed (linear ramp)
  • signal_status     — one of: active | aging | stale
    (invalidation / completion requires price-data backtest — separate
    module, hooked when prices table has coverage for the ticker)

The decay_weight feeds:
  - per-author theme aggregation (recent posts dominate "top tickers")
  - conviction-pick gating (a tracker mentioned 3x but all >60d ago shouldn't
    score as "high conviction")
  - the scoring runner's mention-extraction multiplier (older mentions
    contribute less to a ticker's adjusted score)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Optional


# Timeframe → decay window in days. Calibrated to typical setup half-life
# at that resolution: a 15m chart's edge dies in days; a weekly chart's
# thesis can hold for months. Beyond `window_days`, decay_weight goes to 0.
_TIMEFRAME_WINDOWS = {
    "1m":  3,    "5m":  5,    "15m": 7,
    "30m": 10,   "1h":  14,
    "2h":  21,   "4h":  30,
    "1d":  60,   "D":   60,
    "3d":  90,
    "1w":  120,  "W":   120,
    "1M":  240,  "M":   240,
}

# When timeframe is unknown (Claude couldn't extract), use a swing-style
# midpoint. Tunable per user preference.
_DEFAULT_WINDOW_DAYS = 30


@dataclass
class SignalDecay:
    days_since_chart: Optional[float]
    decay_window: int
    decay_weight: float           # 0.0 — 1.0
    signal_status: str            # active | aging | stale | unknown

    def to_dict(self) -> dict:
        return {
            "days_since_chart": (
                round(self.days_since_chart, 1) if self.days_since_chart is not None else None
            ),
            "decay_window": self.decay_window,
            "decay_weight": round(self.decay_weight, 3),
            "signal_status": self.signal_status,
        }


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        # Accept "2026-05-08", "2026-05-08T18:00:00", "2026-05-08T18:00:00+00:00"
        if "T" not in s and len(s) >= 10:
            s = s[:10] + "T00:00:00+00:00"
        elif "T" in s and "+" not in s and "Z" not in s:
            s = s + "+00:00"
        elif s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _window_for(timeframe: Optional[str]) -> int:
    """Pick the decay window for a chart's resolution."""
    if not timeframe:
        return _DEFAULT_WINDOW_DAYS
    key = str(timeframe).strip()
    # Try exact match, then case-folded
    if key in _TIMEFRAME_WINDOWS:
        return _TIMEFRAME_WINDOWS[key]
    upper = key.upper()
    if upper in _TIMEFRAME_WINDOWS:
        return _TIMEFRAME_WINDOWS[upper]
    lower = key.lower()
    if lower in _TIMEFRAME_WINDOWS:
        return _TIMEFRAME_WINDOWS[lower]
    return _DEFAULT_WINDOW_DAYS


def compute_decay(
    published_at: Optional[str],
    timeframe: Optional[str] = None,
    *,
    now: Optional[datetime] = None,
) -> SignalDecay:
    """Return the time-decay snapshot for one drop.

    `published_at` should be the TradingView chart header date (ISO 8601);
    falls back gracefully to `unknown` status when missing.
    """
    window = _window_for(timeframe)
    pub = _parse_iso(published_at)
    if pub is None:
        return SignalDecay(
            days_since_chart=None,
            decay_window=window,
            decay_weight=0.5,   # neutral default for unknown-age drops
            signal_status="unknown",
        )

    ref = now or datetime.now(UTC)
    if pub.tzinfo is None:
        pub = pub.replace(tzinfo=UTC)
    delta = (ref - pub).total_seconds() / 86400.0  # days
    if delta < 0:
        # Chart timestamp in the future (clock skew or bad parse) — treat as fresh
        delta = 0.0

    # Linear decay 1.0 at 0 days → 0.0 at window
    weight = max(0.0, 1.0 - (delta / window))

    # Status bands: ≥0.66 active, ≥0.33 aging, else stale
    if weight >= 0.66:
        status = "active"
    elif weight >= 0.33:
        status = "aging"
    else:
        status = "stale"

    return SignalDecay(
        days_since_chart=delta,
        decay_window=window,
        decay_weight=weight,
        signal_status=status,
    )


def decay_label(s: SignalDecay) -> str:
    """Short human-readable label for the SPA badge."""
    if s.signal_status == "unknown":
        return "unknown age"
    if s.days_since_chart is None:
        return s.signal_status
    d = s.days_since_chart
    if d < 1.0:
        return "today"
    if d < 2.0:
        return "1d ago"
    if d < 14:
        return f"{int(d)}d ago"
    if d < 60:
        return f"{int(d / 7)}w ago"
    return f"{int(d / 30)}mo ago"

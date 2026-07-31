"""Theme / ticker momentum — the first-derivative layer that turns weekly
mention counts into a ranked "CHECK THIS OUT" feed.

Level-weighting (signal_decay) answers "how much does this still matter?".
Momentum answers the *actionable* question: "what is heating up RIGHT NOW,
before it's obvious?" A ticker going 2 -> 5 -> 11 mentions/week is a lead;
the same ticker going 11 -> 5 -> 2 is exhaust.

Pure functions over a weekly count series `w` (oldest -> newest). No I/O, so
they're trivially testable and reused by both the streams builder and any
future alerting.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Momentum:
    total: int              # sum of mentions across the window
    current: int            # mentions in the most recent week
    velocity: float         # WoW change, current - prev (mentions/week)
    acceleration: float     # 2nd difference — is the rise itself speeding up?
    slope: float            # OLS slope over the whole window (sustained trend)
    surge: float            # current / trailing-baseline (relative jump; 1.0 = flat)
    breakout_score: float   # 0-100 composite; higher = more worth verifying now
    status: str             # breakout | building | peaking | fading | quiet

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "current": self.current,
            "velocity": round(self.velocity, 2),
            "acceleration": round(self.acceleration, 2),
            "slope": round(self.slope, 3),
            "surge": round(self.surge, 2),
            "breakout_score": round(self.breakout_score, 1),
            "status": self.status,
        }


def _ols_slope(y: list[float]) -> float:
    """Least-squares slope of y against 0..n-1. 0 for <2 points."""
    n = len(y)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(y) / n
    num = sum((x - mx) * (v - my) for x, v in zip(xs, y))
    den = sum((x - mx) ** 2 for x in xs)
    return num / den if den else 0.0


# A theme needs at least this many mentions in the current week before it can
# be called a "breakout" — one straggler mention shouldn't light the board.
_MIN_CURRENT_FOR_BREAKOUT = 2


def compute_momentum(weekly: list[int]) -> Momentum:
    """Compute momentum from a weekly count series (oldest -> newest).

    Expects >= 3 weeks for acceleration; degrades gracefully below that.
    """
    w = [max(0, int(x)) for x in weekly]
    total = sum(w)
    current = w[-1] if w else 0
    prev = w[-2] if len(w) >= 2 else 0
    prev2 = w[-3] if len(w) >= 3 else 0

    velocity = float(current - prev)
    # 2nd difference: (current - prev) - (prev - prev2). Positive => the
    # increase is itself accelerating (convex), the classic breakout shape.
    acceleration = float((current - prev) - (prev - prev2))
    slope = _ols_slope([float(x) for x in w])

    # Trailing baseline = mean of every week EXCEPT the current one. Surge is
    # how far the current week pops above its own recent normal.
    if len(w) >= 2:
        baseline = sum(w[:-1]) / (len(w) - 1)
    else:
        baseline = 0.0
    surge = current / max(baseline, 0.5)

    # --- Composite breakout score (0-100) ---
    # Only upside momentum scores; fading themes fall to the bottom.
    surge_c = _clamp((surge - 1.0) / 2.0)          # +100% over baseline -> ~0.5
    accel_c = math.tanh(max(0.0, acceleration) / 2.0)
    slope_c = math.tanh(max(0.0, slope))
    level_c = math.log1p(current) / math.log1p(10)  # absolute volume, ~10 caps
    breakout_score = 100.0 * (
        0.40 * surge_c + 0.30 * accel_c + 0.20 * level_c + 0.10 * slope_c
    )

    status = _classify(current, velocity, acceleration, slope, surge, baseline)
    # Non-breakout states never claim a high score.
    if status in ("fading", "quiet"):
        breakout_score = min(breakout_score, 25.0)

    return Momentum(
        total=total, current=current, velocity=velocity,
        acceleration=acceleration, slope=slope, surge=surge,
        breakout_score=breakout_score, status=status,
    )


def _classify(current, velocity, acceleration, slope, surge, baseline) -> str:
    if current < 1 or (current + baseline) < 1.5:
        return "quiet"
    if (current >= _MIN_CURRENT_FOR_BREAKOUT
            and surge >= 1.8 and acceleration > 0 and velocity > 0):
        return "breakout"          # sudden convex acceleration — verify NOW
    if slope > 0 and velocity >= 0:
        return "building"          # steady climb
    if velocity <= 0 and acceleration < 0 and current >= baseline:
        return "peaking"           # was hot, rolling over
    if slope < 0 and current < baseline:
        return "fading"            # exhaust
    return "building" if slope >= 0 else "fading"


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))

"""Price-action structure — the levels a chart actually has.

The v1 level synthesizer placed stops at a blind 2×ATR and targets at a
flat 3R. Both are conventions, not observations: the target in particular
carried no information about the chart at all, which made the R/R score a
function of *which detector fired* rather than of the trade.

This module extracts the levels a human would draw:

- **Swing pivots** — fractal highs and lows (a bar whose high exceeds the
  `left`/`right` bars either side, and the mirror for lows). These are the
  turning points price actually made.
- **Zones, not lines** — pivots within a tolerance of each other are one
  level. A level tested three times at 82.10 / 82.44 / 81.95 is a zone,
  and the zone's edges are what matters for placing a stop beyond it.
- **Strength** — touches, recency, how long the level has been respected,
  volume transacted there, and whether it *flipped* (old resistance now
  acting as support, which is the strongest kind of level).
- **Round numbers** — psychological levels near price, which is where
  humans cluster orders whether or not the chart has a pivot there.

Everything is derived from OHLCV bars alone; no lookahead, no fitting.
The synthesizer consumes this map and the KOL consensus, and every level
it uses carries a `basis` sentence so the card can say *why* that number.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Fractal width: a pivot must dominate this many bars either side.
_PIVOT_LEFT = 3
_PIVOT_RIGHT = 3

# Pivots within this many ATR of each other are the same zone.
_CLUSTER_ATR = 0.6

# Recency half-life, in bars, for the strength decay.
_RECENCY_HALFLIFE = 45.0

# Touch count at which the touch term saturates.
_TOUCH_SATURATION = 4.0

# Strength term weights (sum to 1.0 before the flip/round bonuses).
_W_TOUCHES = 0.40
_W_RECENCY = 0.30
_W_SPAN = 0.15
_W_VOLUME = 0.15

# Share of a zone's pivots that must be of the opposite kind before it
# counts as a polarity flip rather than a two-sided zone.
_FLIP_MAJORITY = 0.6

# Bonuses, added after the weighted terms and clamped at 1.0.
_FLIP_BONUS = 0.12
_ROUND_BONUS = 0.05


@dataclass
class Level:
    """One horizontal level, as a zone rather than a line."""

    price: float          # zone centre — the number to quote
    low: float            # zone bounds; a stop goes beyond these, not through
    high: float
    kind: str             # "support" | "resistance"
    touches: int
    last_touch_bars: int  # bars since price last tested it
    span_bars: int        # first touch → last touch
    strength: float       # 0..1
    flipped: bool = False
    round_number: bool = False
    basis: str = ""       # human sentence: why this level exists

    @property
    def width(self) -> float:
        return max(0.0, self.high - self.low)


@dataclass
class StructureMap:
    supports: list[Level] = field(default_factory=list)
    resistances: list[Level] = field(default_factory=list)

    @property
    def levels(self) -> list[Level]:
        return [*self.supports, *self.resistances]


# ---------------------------------------------------------------------------
# Pivots
# ---------------------------------------------------------------------------

def swing_pivots(
    highs: list[float],
    lows: list[float],
    *,
    left: int = _PIVOT_LEFT,
    right: int = _PIVOT_RIGHT,
) -> list[dict]:
    """Fractal turning points. Returns [{i, price, kind}] oldest first.

    A pivot high is a bar whose high is >= every high in the `left` bars
    before and > every high in the `right` bars after (strict on the right
    so a flat shelf resolves to its first bar, not every bar in it).
    """
    out: list[dict] = []
    n = min(len(highs), len(lows))
    for i in range(left, n - right):
        h = highs[i]
        if (
            all(h >= highs[j] for j in range(i - left, i))
            and all(h > highs[j] for j in range(i + 1, i + right + 1))
        ):
            out.append({"i": i, "price": h, "kind": "high"})
        lo = lows[i]
        if (
            all(lo <= lows[j] for j in range(i - left, i))
            and all(lo < lows[j] for j in range(i + 1, i + right + 1))
        ):
            out.append({"i": i, "price": lo, "kind": "low"})
    return out


# ---------------------------------------------------------------------------
# Clustering + strength
# ---------------------------------------------------------------------------

def cluster_pivots(pivots: list[dict], tolerance: float) -> list[dict]:
    """Group pivots whose prices sit within `tolerance` into one zone.

    Greedy over price-sorted pivots: a pivot joins the open cluster while
    it stays within tolerance of that cluster's running centre.
    """
    if not pivots or tolerance <= 0:
        return []
    ordered = sorted(pivots, key=lambda p: p["price"])
    clusters: list[list[dict]] = [[ordered[0]]]
    for p in ordered[1:]:
        current = clusters[-1]
        centre = sum(q["price"] for q in current) / len(current)
        if abs(p["price"] - centre) <= tolerance:
            current.append(p)
        else:
            clusters.append([p])
    return [
        {
            "prices": [p["price"] for p in c],
            "indices": [p["i"] for p in c],
            "kinds": [p["kind"] for p in c],
        }
        for c in clusters
    ]


def _recency_weight(bars_ago: int) -> float:
    """1.0 at the current bar, halving every `_RECENCY_HALFLIFE` bars."""
    return 0.5 ** (max(0, bars_ago) / _RECENCY_HALFLIFE)


def _volume_share(
    volumes: list[float], highs: list[float], lows: list[float],
    zone_low: float, zone_high: float,
) -> float:
    """Share of total volume traded on bars that touched the zone.

    A level defended on heavy volume matters more than one brushed on a
    quiet drift — this is the cheap stand-in for a volume profile.
    """
    total = sum(v for v in volumes if v)
    if not total:
        return 0.0
    at_zone = sum(
        v for v, h, lo in zip(volumes, highs, lows)
        if v and lo <= zone_high and h >= zone_low
    )
    return min(1.0, at_zone / total)


# A candidate round-number step must be at least this share of price.
# Without the floor, the magnitude/10 step degenerates to 1 on a $76
# asset and every price on the chart reads as "round".
_MIN_ROUND_STEP_PCT = 0.02

# Round-number tolerance: tight in both ATR and percentage terms.
_ROUND_TOL_ATR = 0.15
_ROUND_TOL_PCT = 0.005


def round_number_steps(price: float) -> list[float]:
    """Psychological step sizes worth checking at this magnitude."""
    if price <= 0:
        return []
    magnitude = 10 ** (len(f"{int(price)}") - 1) if price >= 1 else 0.1
    steps = [magnitude, magnitude / 2, magnitude / 10]
    return [s for s in steps if s > 0 and s >= _MIN_ROUND_STEP_PCT * price]


def is_round_number(price: float, atr: float) -> bool:
    """Within a tight band of a psychological level (2,400 for ETH, 200
    for COIN) — where humans cluster orders regardless of the chart."""
    if price <= 0 or not atr or atr <= 0:
        return False
    tolerance = min(_ROUND_TOL_ATR * atr, _ROUND_TOL_PCT * price)
    for step in round_number_steps(price):
        nearest = round(price / step) * step
        if abs(price - nearest) <= tolerance:
            return True
    return False


def _describe(level: Level) -> str:
    """The sentence the card shows instead of a bare number."""
    times = "once" if level.touches == 1 else f"{level.touches}×"
    when = (
        "tested this bar" if level.last_touch_bars <= 1
        else f"last tested {level.last_touch_bars} bars ago"
    )
    bits = [f"{level.kind} {level.price:.4g}, held {times}, {when}"]
    if level.flipped:
        bits.append("flipped from the other side")
    if level.round_number:
        bits.append("round number")
    return "; ".join(bits)


def build_structure(
    bars: list,
    atr: float | None,
    *,
    last_close: float | None = None,
) -> StructureMap:
    """Extract support/resistance zones from OHLCV bars.

    Levels are classified against the LAST close: zones below are support,
    zones above are resistance — with `flipped` marking a zone built from
    pivots of the opposite kind (old resistance now sitting under price is
    the classic flip, and the strongest level on the chart).
    """
    if not bars or not atr or atr <= 0:
        return StructureMap()

    highs = [(b.high if b.high is not None else b.close) for b in bars]
    lows = [(b.low if b.low is not None else b.close) for b in bars]
    volumes = [float(b.volume or 0) for b in bars]
    n = len(bars)
    close = last_close if last_close is not None else bars[-1].close
    if not close:
        return StructureMap()

    pivots = swing_pivots(highs, lows)
    if not pivots:
        return StructureMap()

    supports: list[Level] = []
    resistances: list[Level] = []

    for cluster in cluster_pivots(pivots, _CLUSTER_ATR * atr):
        prices = cluster["prices"]
        indices = cluster["indices"]
        kinds = cluster["kinds"]
        centre = sum(prices) / len(prices)
        zone_low, zone_high = min(prices), max(prices)
        touches = len(prices)
        last_touch_bars = n - 1 - max(indices)
        span_bars = max(indices) - min(indices)

        # Strength: how much this level has earned attention.
        touch_term = min(1.0, touches / _TOUCH_SATURATION)
        recency_term = _recency_weight(last_touch_bars)
        span_term = min(1.0, span_bars / max(1, n / 2))
        volume_term = _volume_share(volumes, highs, lows, zone_low, zone_high)
        strength = (
            _W_TOUCHES * touch_term
            + _W_RECENCY * recency_term
            + _W_SPAN * span_term
            + _W_VOLUME * volume_term
        )

        kind = "support" if centre < close else "resistance"
        # Polarity flip: a zone built predominantly from HIGHS now sitting
        # below price (old resistance turned support), or the mirror. A
        # mixed zone that has acted as both is not a flip — it needs a
        # clear majority, or the tie-break invents one.
        highs_share = kinds.count("high") / touches
        flipped = (
            (kind == "support" and highs_share >= _FLIP_MAJORITY)
            or (kind == "resistance" and (1 - highs_share) >= _FLIP_MAJORITY)
        )
        round_number = is_round_number(centre, atr)

        strength += (_FLIP_BONUS if flipped else 0.0)
        strength += (_ROUND_BONUS if round_number else 0.0)

        level = Level(
            price=centre,
            low=zone_low,
            high=zone_high,
            kind=kind,
            touches=touches,
            last_touch_bars=last_touch_bars,
            span_bars=span_bars,
            strength=round(min(1.0, strength), 4),
            flipped=flipped,
            round_number=round_number,
        )
        level.basis = _describe(level)
        (supports if kind == "support" else resistances).append(level)

    supports.sort(key=lambda x: x.price, reverse=True)   # nearest below first
    resistances.sort(key=lambda x: x.price)              # nearest above first
    return StructureMap(supports=supports, resistances=resistances)


# ---------------------------------------------------------------------------
# Queries the synthesizer needs
# ---------------------------------------------------------------------------

def nearest_support(
    structure: StructureMap, price: float, *, min_strength: float = 0.0
) -> Level | None:
    """Strongest-qualifying support at or below `price`, nearest first."""
    for lv in structure.supports:
        if lv.price <= price and lv.strength >= min_strength:
            return lv
    return None


def next_resistance(
    structure: StructureMap,
    price: float,
    *,
    min_distance: float = 0.0,
    min_strength: float = 0.0,
) -> Level | None:
    """First resistance above `price` + `min_distance` worth targeting.

    `min_distance` keeps a target from landing on a level so close that
    the trade can't pay for its own risk.
    """
    floor = price + min_distance
    for lv in structure.resistances:
        if lv.price >= floor and lv.strength >= min_strength:
            return lv
    return None


def next_support_below(
    structure: StructureMap,
    price: float,
    *,
    min_distance: float = 0.0,
    min_strength: float = 0.0,
) -> Level | None:
    """Mirror of `next_resistance` for short-side targets."""
    ceiling = price - min_distance
    for lv in structure.supports:
        if lv.price <= ceiling and lv.strength >= min_strength:
            return lv
    return None


def nearest_resistance(
    structure: StructureMap, price: float, *, min_strength: float = 0.0
) -> Level | None:
    """Strongest-qualifying resistance at or above `price` — the level a
    short's invalidation sits beyond."""
    for lv in structure.resistances:
        if lv.price >= price and lv.strength >= min_strength:
            return lv
    return None

"""Technical agent — entry/stop/target synthesis (v0 mechanical + v1 structure).

This is the "levels pending" killer. Given the flat feature dict from
`prices.technicals.compute_technical_features`, produce a LevelSet the
scoring pass can persist and the dashboard can render.

Design (per the technical-agent brief, .claude/context/briefs/technical-agent.md):

- v1 structure-aware detectors run first, in priority order. Stops sit
  below/above *invalidation* (the broken level, the defended support),
  not at a blind ATR multiple.
- When no structural entry exists we do NOT fabricate structure: we fall
  back to mechanical ATR rails, honestly labeled ``mechanical_v0`` with
  ``structural=False`` so every consumer (UI, rules gate, journal) can
  tell a real setup from placeholder rails.
- No price or no ATR → no levels at all (None + reason), never fake ones.

Sanity clamps: structural stops are only trusted when they put risk in
the [0.75, 3.5] ATR band. Tighter reads as noise (a stop that a normal
day's range would hit); wider means the structure is too far away to be
this trade's invalidation — both fall back to mechanical rails.

v2 (personalization: KOL level cross-check weighted by setup_win_rate,
gold-label placement priors, rules-gate routing) builds on this module —
see the brief.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Risk band (in ATR multiples) inside which a structural stop is trusted.
_MIN_RISK_ATR = 0.75
_MAX_RISK_ATR = 3.5

# Mechanical (v0) conventions: 2×ATR stop, 3R target.
_MECH_STOP_ATR = 2.0
_MECH_TARGET_R = 3.0

# Structural targets: minimum R multiple when projecting into open field.
_STRUCT_TARGET_R = 2.5

# How close (in ATR) price must be to a support/resistance MA for the
# pullback / rally detectors to consider it "at structure".
_NEAR_STRUCTURE_ATR = 1.0


@dataclass
class LevelSet:
    """One proposed set of trade levels. Levels are decision support —
    nothing here auto-executes (brief non-goal #1)."""

    side: str          # "LONG" | "SHORT"
    entry: float
    stop: float
    target: float
    rr: float          # (target-entry)/(entry-stop), sign-normalized
    method: str        # mechanical_v0 | breakout_20d | pullback_support |
                       # breakdown_20d | rally_resistance
    setup: str         # human label for the UI card
    structural: bool   # True when a structure detector produced the stop
    version: str = "v1"
    notes: list[str] = field(default_factory=list)

    @property
    def risk_pct(self) -> float:
        """Distance to invalidation as a fraction of entry (sizing input)."""
        if not self.entry:
            return 0.0
        return abs(self.entry - self.stop) / self.entry

    def to_dict(self) -> dict:
        return {
            "side": self.side,
            "entry": round(self.entry, 6),
            "stop": round(self.stop, 6),
            "target": round(self.target, 6),
            "rr": round(self.rr, 3),
            "risk_pct": round(self.risk_pct, 5),
            "method": self.method,
            "setup": self.setup,
            "structural": self.structural,
            "version": self.version,
            "notes": self.notes,
        }


def _rr(entry: float, stop: float, target: float) -> float:
    risk = abs(entry - stop)
    if risk <= 0:
        return 0.0
    return abs(target - entry) / risk


def side_from_signal_bias(signal_aggregate: dict | None) -> str:
    """Derive the level side from the aggregated tracked-voice bias.

    Only a confident short consensus flips us short; everything else
    (long / neutral / exit_bias / watch_only / missing) synthesizes LONG
    rails — the watchlist is long-biased by construction and exit/watch
    biases are not directional conviction.
    """
    agg = signal_aggregate or {}
    direction = (agg.get("bias_direction") or "").lower()
    confidence = float(agg.get("bias_confidence") or 0.0)
    if direction == "short" and confidence >= 0.6:
        return "SHORT"
    return "LONG"


def synthesize_levels(
    feats: dict,
    side: str = "LONG",
) -> tuple[LevelSet | None, str | None]:
    """Synthesize levels from technical features.

    Returns (LevelSet, None) on success, (None, reason) when no honest
    levels can be produced (no price bars / no ATR).
    """
    close = feats.get("close")
    atr = feats.get("atr14")
    if not close or close <= 0:
        return None, "no_price"
    if not atr or atr <= 0:
        return None, "no_atr"

    if side == "SHORT":
        level_set = _synthesize_short(feats, float(close), float(atr))
    else:
        level_set = _synthesize_long(feats, float(close), float(atr))
    return level_set, None


# ---------------------------------------------------------------------------
# LONG
# ---------------------------------------------------------------------------

def _synthesize_long(feats: dict, close: float, atr: float) -> LevelSet:
    entry = close

    # 1. Breakout continuation — last bar pierced the prior 20-bar high.
    #    Invalidation = the broken level: if price falls back below it the
    #    breakout failed. Stop half an ATR under it for wick room.
    prior_high = feats.get("prior_high_20")
    if feats.get("recent_breakout") and prior_high and prior_high < entry:
        stop = float(prior_high) - 0.5 * atr
        risk = entry - stop
        if _MIN_RISK_ATR * atr <= risk <= _MAX_RISK_ATR * atr:
            target = entry + _MECH_TARGET_R * risk  # open field above 20d high
            return LevelSet(
                side="LONG", entry=entry, stop=stop,
                target=target, rr=_rr(entry, stop, target),
                method="breakout_20d", setup="20-bar breakout",
                structural=True,
                notes=[
                    f"breakout over {prior_high:.4g}; stop below broken level",
                ],
            )

    # 2. Pullback to support — uptrend intact, price sitting at/near a
    #    rising MA. Invalidation = losing both the support MA and the
    #    recent swing low.
    uptrend = bool(feats.get("above_ma50")) and (
        bool(feats.get("higher_lows")) or bool(feats.get("above_ema50"))
    )
    if uptrend:
        supports = [
            feats.get("ema20"), feats.get("ma20"), feats.get("ma50"),
        ]
        near = [
            s for s in supports
            if s and abs(entry - s) <= _NEAR_STRUCTURE_ATR * atr
        ]
        if near:
            support = min(near)  # deepest nearby support = invalidation
            swing_low = feats.get("swing_low_10")
            invalidation = min(support, swing_low) if swing_low else support
            stop = float(invalidation) - 0.5 * atr
            risk = entry - stop
            if _MIN_RISK_ATR * atr <= risk <= _MAX_RISK_ATR * atr:
                # First objective is the prior 20-bar high when it's
                # meaningfully above; otherwise project a minimum-R move.
                prior_high = feats.get("prior_high_20")
                floor_target = entry + _STRUCT_TARGET_R * risk
                target = (
                    float(prior_high)
                    if prior_high and prior_high > floor_target
                    else floor_target
                )
                return LevelSet(
                    side="LONG", entry=entry, stop=stop,
                    target=target, rr=_rr(entry, stop, target),
                    method="pullback_support", setup="pullback to support",
                    structural=True,
                    notes=[
                        f"support {support:.4g}; stop below swing low + support",
                    ],
                )

    # 3. Mechanical rails (v0) — no structural entry here; honest label.
    stop = entry - _MECH_STOP_ATR * atr
    risk = entry - stop
    target = entry + _MECH_TARGET_R * risk
    return LevelSet(
        side="LONG", entry=entry, stop=stop,
        target=target, rr=_rr(entry, stop, target),
        method="mechanical_v0", setup="mechanical rails",
        structural=False,
        notes=["2×ATR stop / 3R target — placeholder until structure forms"],
    )


# ---------------------------------------------------------------------------
# SHORT
# ---------------------------------------------------------------------------

def _synthesize_short(feats: dict, close: float, atr: float) -> LevelSet:
    entry = close

    # 1. Breakdown continuation — mirror of the breakout.
    prior_low = feats.get("prior_low_20")
    if feats.get("recent_breakdown") and prior_low and prior_low > entry:
        stop = float(prior_low) + 0.5 * atr
        risk = stop - entry
        if _MIN_RISK_ATR * atr <= risk <= _MAX_RISK_ATR * atr:
            target = entry - _MECH_TARGET_R * risk
            return LevelSet(
                side="SHORT", entry=entry, stop=stop,
                target=target, rr=_rr(entry, stop, target),
                method="breakdown_20d", setup="20-bar breakdown",
                structural=True,
                notes=[
                    f"breakdown under {prior_low:.4g}; stop above broken level",
                ],
            )

    # 2. Rally into resistance — downtrend intact, price back at a
    #    declining MA. Invalidation = reclaiming resistance + swing high.
    downtrend = not feats.get("above_ma50", False) and (
        bool(feats.get("lower_highs")) or not feats.get("above_ema50", True)
    )
    if downtrend:
        resistances = [
            feats.get("ema20"), feats.get("ma20"), feats.get("ma50"),
        ]
        near = [
            r for r in resistances
            if r and abs(entry - r) <= _NEAR_STRUCTURE_ATR * atr
        ]
        if near:
            resistance = max(near)
            swing_high = feats.get("swing_high_10")
            invalidation = max(resistance, swing_high) if swing_high else resistance
            stop = float(invalidation) + 0.5 * atr
            risk = stop - entry
            if _MIN_RISK_ATR * atr <= risk <= _MAX_RISK_ATR * atr:
                prior_low = feats.get("prior_low_20")
                floor_target = entry - _STRUCT_TARGET_R * risk
                target = (
                    float(prior_low)
                    if prior_low and prior_low < floor_target
                    else floor_target
                )
                return LevelSet(
                    side="SHORT", entry=entry, stop=stop,
                    target=target, rr=_rr(entry, stop, target),
                    method="rally_resistance", setup="rally into resistance",
                    structural=True,
                    notes=[
                        f"resistance {resistance:.4g}; stop above swing high",
                    ],
                )

    # 3. Mechanical rails (v0), short side.
    stop = entry + _MECH_STOP_ATR * atr
    risk = stop - entry
    target = entry - _MECH_TARGET_R * risk
    return LevelSet(
        side="SHORT", entry=entry, stop=stop,
        target=target, rr=_rr(entry, stop, target),
        method="mechanical_v0", setup="mechanical rails",
        structural=False,
        notes=["2×ATR stop / 3R target — placeholder until structure forms"],
    )

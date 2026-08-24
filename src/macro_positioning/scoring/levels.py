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

v2 adds the two things v1 was missing, both optional so the module still
works on price alone:

- **Structure** (`prices.structure`): real swing zones — where price
  actually turned, how often it held, how recently, on what volume. Stops
  clear the far edge of a zone rather than a single line; targets are the
  next overhead supply zone rather than an arithmetic multiple.
- **Trusted voices** (`scoring.kol_levels`): levels the operator's own
  followed sources drew, weighted by each author's backtested
  setup_win_rate, with attribution.

Neither is adopted blindly. Every borrowed level passes a sanity gate —
right side of price, inside the risk band, close enough to be about
today's chart — and anything rejected is recorded with its reason rather
than silently dropped. When no overhead structure exists (a name at all-
time highs) the R-multiple projection returns, labelled as the open-field
convention it is instead of posing as a level.
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

# --- v2: structure + trusted-voice fusion ---------------------------------

# Buffer beyond a zone's far edge for a stop. Structure invalidates when
# the ZONE breaks, not when its centre is touched.
_ZONE_STOP_ATR = 0.35

# A target must clear this multiple of risk to be worth taking.
_MIN_TARGET_R = 1.5

# Ignore wisps: a resistance zone below this strength is not supply worth
# targeting.
_MIN_TARGET_STRENGTH = 0.25

# A borrowed (KOL) level must sit within this many ATR of price to be
# about today's chart rather than a call from a different regime.
_KOL_MAX_DISTANCE_ATR = 12.0

# Structure and a human agreeing inside this band is agreement, not two
# different levels.
_AGREEMENT_ATR = 0.5


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
    # One entry per rail: where the number came from and why. This is what
    # the card renders instead of an unexplained price.
    provenance: list[dict] = field(default_factory=list)
    # Levels that were considered and refused, with the reason — a stale
    # KOL target should be visible as rejected, not silently absent.
    rejected: list[dict] = field(default_factory=list)

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
            "provenance": self.provenance,
            "rejected": self.rejected,
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
    *,
    structure=None,
    kol=None,
) -> tuple[LevelSet | None, str | None]:
    """Synthesize levels from technical features.

    `structure` (a `prices.structure.StructureMap`) and `kol` (a
    `scoring.kol_levels.KolLevels`) are optional: given either, the rails
    are re-derived from real chart levels and trusted-voice consensus and
    the result is version "v2". Given neither, this is the v1 behaviour —
    detector + ATR — so a caller with nothing but bars still works.

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

    if structure is not None or kol is not None:
        level_set = _apply_context(
            level_set, feats=feats, atr=float(atr),
            structure=structure, kol=kol,
        )
    return level_set, None


# ---------------------------------------------------------------------------
# v2 — structure + trusted-voice fusion
# ---------------------------------------------------------------------------

def _sign(side: str) -> int:
    """+1 for a long (profit above entry), −1 for a short."""
    return -1 if side == "SHORT" else 1


def _gate_kol(
    consensus,
    *,
    role: str,
    side: str,
    entry: float,
    atr: float,
) -> tuple[float | None, dict | None]:
    """Sanity-check a human level before it is allowed anywhere near a rail.

    Real data makes this mandatory: a 60-day-old BTC stop at 69,000 drawn
    when price was 57,000 is not today's invalidation, and a SOL target
    below spot is a call that already played out. Returns (price, reason)
    where exactly one is set.
    """
    if consensus is None:
        return None, None
    price = consensus.price
    d = _sign(side)
    reject = lambda why: (None, {  # noqa: E731 - terse by design, one shape
        "role": role, "value": round(price, 6), "source": "trusted_voices",
        "reason": why, "who": consensus.basis,
    })

    if abs(price - entry) > _KOL_MAX_DISTANCE_ATR * atr:
        return reject("drawn too far from current price — different regime")
    if role == "target" and (price - entry) * d <= 0:
        return reject("target is behind price — the call already played out")
    if role == "stop" and (entry - price) * d <= 0:
        return reject("stop is on the wrong side of price for this direction")
    if role == "stop":
        risk = abs(entry - price)
        if not (_MIN_RISK_ATR * atr <= risk <= _MAX_RISK_ATR * atr):
            return reject("stop implies risk outside the tradeable band")
    return price, None


def _structure_target(
    structure,
    *,
    side: str,
    entry: float,
    risk: float,
) -> tuple[float | None, object | None]:
    """The next supply (or demand) zone worth exiting into.

    Targets the NEAR edge of the zone: you sell into the zone, not through
    it. Must clear `_MIN_TARGET_R` of risk or it cannot pay for the trade.
    """
    if structure is None or risk <= 0:
        return None, None
    from macro_positioning.prices.structure import next_resistance, next_support_below

    min_distance = _MIN_TARGET_R * risk
    if side == "SHORT":
        level = next_support_below(
            structure, entry, min_distance=min_distance,
            min_strength=_MIN_TARGET_STRENGTH,
        )
        return (level.high if level else None), level
    level = next_resistance(
        structure, entry, min_distance=min_distance,
        min_strength=_MIN_TARGET_STRENGTH,
    )
    return (level.low if level else None), level


def _apply_context(
    level_set: LevelSet,
    *,
    feats: dict,
    atr: float,
    structure=None,
    kol=None,
) -> LevelSet:
    """Upgrade a v1 LevelSet with structure and trusted-voice levels.

    Order of authority, and why:
    1. **Structure decides the stop.** Invalidation is a property of the
       chart, not of an opinion — if a real zone sits under the entry, the
       stop clears its far edge.
    2. **Structure proposes the target**, because supply is where a move
       stalls. Only when the chart has nothing overhead (a name at highs)
       does the R-multiple return, and then it says so.
    3. **Trusted voices break the tie.** A gated human target that is
       nearer than the structural one wins — taking profit earlier than
       the chart allows is the conservative error. A human target with no
       structural competition is used outright when it passes the gate.
    """
    d = _sign(level_set.side)
    entry = level_set.entry
    prov: list[dict] = []
    rejected: list[dict] = []

    prov.append({
        "role": "entry", "value": round(entry, 6), "source": level_set.method,
        "basis": f"{level_set.setup} — entry at {entry:.6g}",
    })

    # --- stop: structure first -------------------------------------------
    stop = level_set.stop
    stop_source = level_set.method if level_set.structural else "mechanical_v0"
    stop_basis = (
        level_set.notes[0] if level_set.notes else "2×ATR below entry"
    )
    if structure is not None:
        from macro_positioning.prices.structure import (
            nearest_resistance,
            nearest_support,
        )
        zone = (
            nearest_resistance(structure, entry) if level_set.side == "SHORT"
            else nearest_support(structure, entry)
        )
        if zone is not None:
            edge = zone.low if level_set.side != "SHORT" else zone.high
            candidate = edge - d * _ZONE_STOP_ATR * atr
            risk = abs(entry - candidate)
            if _MIN_RISK_ATR * atr <= risk <= _MAX_RISK_ATR * atr:
                stop = candidate
                stop_source = "structure"
                stop_basis = zone.basis
                level_set.structural = True
            else:
                rejected.append({
                    "role": "stop", "value": round(candidate, 6),
                    "source": "structure", "reason": (
                        "zone too close to price to be invalidation"
                        if risk < _MIN_RISK_ATR * atr
                        else "zone too far — that risk is a different trade"
                    ),
                    "who": zone.basis,
                })

    kol_stop, kol_stop_reject = _gate_kol(
        getattr(kol, "stop", None), role="stop", side=level_set.side,
        entry=entry, atr=atr,
    )
    if kol_stop_reject:
        rejected.append(kol_stop_reject)
    elif kol_stop is not None:
        agrees = abs(kol_stop - stop) <= _AGREEMENT_ATR * atr
        if stop_source == "structure" or agrees:
            # Structure keeps the stop; the human is corroboration.
            prov.append({
                "role": "stop_crosscheck", "value": round(kol_stop, 6),
                "source": "trusted_voices",
                "basis": ("agrees with the level" if agrees
                          else "differs from the structural invalidation"),
                "who": kol.stop.basis,
                "contributors": [c.__dict__ for c in kol.stop.contributors[:4]],
            })
        else:
            stop, stop_source, stop_basis = kol_stop, "trusted_voices", kol.stop.basis

    risk = abs(entry - stop)
    prov.append({
        "role": "stop", "value": round(stop, 6), "source": stop_source,
        "basis": stop_basis,
    })

    # --- target: structure, then trusted voices, then open field ---------
    struct_target, zone = _structure_target(
        structure, side=level_set.side, entry=entry, risk=risk
    )
    kol_target, kol_target_reject = _gate_kol(
        getattr(kol, "target", None), role="target", side=level_set.side,
        entry=entry, atr=atr,
    )
    if kol_target_reject:
        rejected.append(kol_target_reject)

    if struct_target is not None and kol_target is not None:
        agrees = abs(struct_target - kol_target) <= _AGREEMENT_ATR * atr
        nearer_human = (kol_target - struct_target) * d < 0
        if agrees or not nearer_human:
            target, t_source, t_basis = struct_target, "structure", zone.basis
            prov.append({
                "role": "target_crosscheck", "value": round(kol_target, 6),
                "source": "trusted_voices",
                "basis": "agrees with the zone" if agrees else "reaches beyond the zone",
                "who": kol.target.basis,
                "contributors": [c.__dict__ for c in kol.target.contributors[:4]],
            })
        else:
            # Humans see the move stalling sooner than the chart does.
            target, t_source, t_basis = kol_target, "trusted_voices", kol.target.basis
            prov.append({
                "role": "target_crosscheck", "value": round(struct_target, 6),
                "source": "structure", "basis": f"zone beyond the call: {zone.basis}",
            })
    elif struct_target is not None:
        target, t_source, t_basis = struct_target, "structure", zone.basis
    elif kol_target is not None:
        target, t_source, t_basis = kol_target, "trusted_voices", kol.target.basis
    else:
        target = entry + d * _MECH_TARGET_R * risk
        t_source = "open_field"
        t_basis = (
            f"no {'demand' if level_set.side == 'SHORT' else 'supply'} zone in range "
            f"— {_MECH_TARGET_R:.0f}R projection"
        )

    prov.append({
        "role": "target", "value": round(target, 6), "source": t_source,
        "basis": t_basis,
        **({"contributors": [c.__dict__ for c in kol.target.contributors[:4]]}
           if t_source == "trusted_voices" else {}),
    })

    # --- entry corroboration (never overrides; the detector owns entry) ---
    kol_entry, kol_entry_reject = _gate_kol(
        getattr(kol, "entry", None), role="entry", side=level_set.side,
        entry=entry, atr=atr,
    )
    if kol_entry_reject:
        rejected.append(kol_entry_reject)
    elif kol_entry is not None:
        prov.append({
            "role": "entry_crosscheck", "value": round(kol_entry, 6),
            "source": "trusted_voices",
            "basis": f"{(kol_entry - entry) / entry * 100:+.1f}% vs the agent entry",
            "who": kol.entry.basis,
            "contributors": [c.__dict__ for c in kol.entry.contributors[:4]],
        })

    level_set.stop = stop
    level_set.target = target
    level_set.rr = _rr(entry, stop, target)
    level_set.version = "v2"
    level_set.provenance = prov
    level_set.rejected = rejected

    # Method is the machine-readable trail of what contributed.
    if t_source == "structure" or stop_source == "structure":
        level_set.method = f"{level_set.method}+structure"
    if "trusted_voices" in (t_source, stop_source):
        level_set.method = f"{level_set.method}+voices"

    # The card's label must describe the rails it is actually showing:
    # "mechanical rails" is wrong once the stop sits on a real zone.
    if stop_source == "structure" and level_set.setup == "mechanical rails":
        base = "structure rails"
    elif stop_source == "trusted_voices":
        base = f"{level_set.setup} · voice stop"
    else:
        base = level_set.setup
    if t_source == "trusted_voices":
        base += " · voice target"
    elif t_source == "open_field":
        base += " · open-field target"
    level_set.setup = base
    return level_set


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

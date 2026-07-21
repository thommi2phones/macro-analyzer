"""Signal Alignment — heuristic, no LLM.

Scores the *tracked-voice conviction* axis: do the sources this system
follows (KOL chart calls, insider filings, newsletters) collectively
support going LONG this ticker right now? This is the project's core
differentiator — the other eight components score the setup's technical
and macro quality impersonally; this one scores *who is positioning in
it, how hard, how recently, and whether they agree.*

Input: `setup.signal_aggregate`, the output of
`signals.aggregation.aggregate_for_ticker()`. Relevant fields:
  - net_bias        : long_weight − short_weight (trust×recency weighted)
  - bias_direction  : long | short | neutral | exit_bias | watch_only
  - bias_confidence : 0..1 share of directional conviction on the winning side
  - alignment_score : 0..10 positive directional conviction (long side only)
  - n_signals       : how many active signals fed the aggregate
  - avoid_count     : explicit "avoid this" voices (not directional)

Mapping to a flat 0..1 sub-signal (0.5 = neutral / no signal):

    signed = clamp(net_bias / _SCALE, -1, +1)
    value  = 0.5 + 0.5 * signed

`_SCALE` mirrors `aggregation._alignment_score`'s scale (12.0) so a net
bias that would read ~10/10 there lands near 1.0 here. net_bias already
nets long against short, so a split crowd (long≈short) collapses toward
0.5 — disagreement reads as *no conviction*, which is correct.

A net-neutral aggregate carrying explicit AVOID voices is nudged below
0.5: the tracked voices are actively saying "stay away" even though no
directional long/short bias exists.

Missing / empty aggregate → 0.5 with a note (no tracked signal is not
evidence against the setup).
"""

from __future__ import annotations

from macro_brain.agents._heuristic_log import with_log
from macro_brain.types import SetupContext, SubScore

VERSION = "signal_alignment@v1"

# Net-bias magnitude that maps to full directional tilt (value 0 or 1).
# Kept in sync with signals.aggregation._alignment_score's scale so the
# raw 0..10 alignment_score and this 0..1 value tell a consistent story.
_SCALE = 12.0

# Each explicit AVOID voice pulls a net-neutral score down by this much.
_AVOID_PENALTY = 0.1


def _compute(agg: dict) -> SubScore:
    n_signals = int(agg.get("n_signals") or 0)
    if not agg or n_signals == 0:
        return SubScore(
            component="signal_alignment",
            value=0.5,
            contributing_features={"n_signals": 0.0},
            notes="No tracked signals for this ticker.",
        )

    net_bias = float(agg.get("net_bias") or 0.0)
    signed = max(-1.0, min(1.0, net_bias / _SCALE))
    value = 0.5 + 0.5 * signed

    # Voices explicitly calling to avoid the name push a directionless
    # aggregate below neutral (they carry no long/short weight, so
    # net_bias alone wouldn't reflect them).
    avoid_count = int(agg.get("avoid_count") or 0)
    if avoid_count and net_bias <= 0:
        value -= _AVOID_PENALTY * avoid_count

    value = max(0.0, min(1.0, value))

    direction = agg.get("bias_direction") or "neutral"
    confidence = float(agg.get("bias_confidence") or 0.0)
    catalyst = agg.get("dominant_catalyst") or "?"
    return SubScore(
        component="signal_alignment",
        value=value,
        contributing_features={
            "net_bias": net_bias,
            "long_weight": float(agg.get("long_weight") or 0.0),
            "short_weight": float(agg.get("short_weight") or 0.0),
            "bias_confidence": confidence,
            "alignment_score_raw": float(agg.get("alignment_score") or 0.0),
            "n_signals": float(n_signals),
            "avoid_count": float(avoid_count),
        },
        notes=(
            f"{direction} bias ({confidence:.0%} conf) across {n_signals} "
            f"signal(s); catalyst={catalyst}."
        ),
    )


def score_signal_alignment(setup: SetupContext) -> SubScore:
    agg = setup.signal_aggregate or {}
    return with_log(
        agent_name="signal_alignment",
        version=VERSION,
        input_features=agg,
        fn=lambda: _compute(agg),
    )

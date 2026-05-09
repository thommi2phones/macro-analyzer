"""Volume Flow Confirmation — heuristic, no LLM.

Reads `setup.volume_features` (produced by
`macro_positioning.prices.technicals.compute_volume_features`) and
emits a SubScore for `volume_flow_confirmation`.

Signal: is recent volume confirming the current price move?
  ratio = vol_5d_avg / vol_20d_avg
  - ratio > 1 on a rally → bullish confirmation
  - ratio > 1 on a sell-off → bearish confirmation (capitulation /
    distribution); from a long-bias scorer perspective that's BEARISH
    for the setup, so we sign the lift by direction of pct_change_5d
  - ratio < 1 on a rally → weak rally, no commitment
  - ratio < 1 on a sell-off → fading sell pressure (mildly bullish)

Output 0..1: 0.5 + 0.5 * tanh(sign(pct_5d) * (ratio - 1) * gain).
"""

from __future__ import annotations

import math

from macro_brain.agents._heuristic_log import with_log
from macro_brain.types import SetupContext, SubScore

VERSION = "volume_flow_confirmation@v1"
_GAIN = 1.5


def _compute(feats: dict) -> SubScore:
    n = feats.get("n_volume_bars") or 0
    if n < 20:
        return SubScore(
            component="volume_flow_confirmation",
            value=0.5,
            contributing_features={"n_volume_bars": float(n)},
            notes=f"Insufficient volume history ({n} bars).",
        )
    vol_5 = feats.get("vol_5d_avg")
    vol_20 = feats.get("vol_20d_avg")
    pct5 = feats.get("pct_change_5d")

    if not vol_20 or vol_20 <= 0 or vol_5 is None or pct5 is None:
        return SubScore(
            component="volume_flow_confirmation",
            value=0.5,
            contributing_features={"n_volume_bars": float(n)},
            notes="Volume averages unavailable or zero.",
        )

    ratio = vol_5 / vol_20
    direction = 1.0 if pct5 >= 0 else -1.0
    signed = direction * (ratio - 1.0)
    value = 0.5 + 0.5 * math.tanh(signed * _GAIN)
    value = max(0.0, min(1.0, value))

    if ratio > 1.05 and pct5 > 0:
        note = f"Vol expansion ({ratio:.2f}x) confirms rally (+{pct5*100:.1f}%)."
    elif ratio > 1.05 and pct5 < 0:
        note = f"Vol expansion ({ratio:.2f}x) on sell-off ({pct5*100:.1f}%) — distribution."
    elif ratio < 0.95 and pct5 > 0:
        note = f"Vol fade ({ratio:.2f}x) on rally — weak commitment."
    elif ratio < 0.95 and pct5 < 0:
        note = f"Vol fade ({ratio:.2f}x) on sell-off — pressure easing."
    else:
        note = f"Vol ratio {ratio:.2f}x near baseline."

    return SubScore(
        component="volume_flow_confirmation",
        value=value,
        contributing_features={
            "n_volume_bars": float(n),
            "vol_5d_avg": float(vol_5),
            "vol_20d_avg": float(vol_20),
            "vol_ratio": float(ratio),
            "pct_change_5d": float(pct5),
        },
        notes=note,
    )


def score_volume_flow_confirmation(setup: SetupContext) -> SubScore:
    feats = setup.volume_features or {}
    return with_log(
        agent_name="volume_flow_confirmation",
        version=VERSION,
        input_features=feats,
        fn=lambda: _compute(feats),
    )

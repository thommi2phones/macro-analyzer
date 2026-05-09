"""Flat feature vector ↔ weighted display score helpers.

Per the hybrid-scoring decision (D-2026-05-08-005):
- Internal: every sub-signal stored as 0.0 ... 1.0
- Display: weighted 0..100 score per framework §10
- Future: weights become learned parameters per regime once outcome
  data accrues. The same flat vector flows through learning code.

This module is intentionally pure (no I/O) so it tests in microseconds
and slots into both online scoring and offline backtests.
"""

from __future__ import annotations

from macro_brain.types import COMPONENT_WEIGHTS, ScoreComponent, SubScore


def to_weighted_int(component: ScoreComponent, value: float) -> int:
    """Convert a flat 0..1 sub-signal to its weighted integer score.

    Example: macro_alignment value=0.85 → 17 (85% of 20pt budget).
    Rounds half-up.
    """
    if value < 0.0:
        value = 0.0
    elif value > 1.0:
        value = 1.0
    weight = COMPONENT_WEIGHTS[component]
    return int(round(value * weight))


def compose_weighted_scores(sub_scores: list[SubScore]) -> dict[ScoreComponent, int]:
    """Convert a list of SubScore to the per-component integer scores.

    Missing components default to 0 (not present = no signal).
    Duplicate components: later entries win (caller's responsibility
    to dedupe upstream).
    """
    out: dict[ScoreComponent, int] = {c: 0 for c in COMPONENT_WEIGHTS}
    for ss in sub_scores:
        out[ss.component] = to_weighted_int(ss.component, ss.value)
    return out


def raw_total(weighted: dict[ScoreComponent, int]) -> int:
    """Sum of weighted component scores. Bounded 0..100."""
    return sum(weighted.values())


def assign_grade(score: int) -> str:
    """Per framework §10 score_interpretation."""
    if score >= 90:
        return "A_plus"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B"
    if score >= 60:
        return "C"
    if score >= 50:
        return "D"
    return "avoid"


def assign_position_size_tier(score: int, *, invalidation_defined: bool) -> str:
    """Per framework §9 position_sizing_framework.

    Tier_4 (avoid) override: any setup without a defined invalidation
    is non-actionable regardless of score.
    """
    if not invalidation_defined or score < 55:
        return "avoid"
    if score >= 85:
        return "tier_1"
    if score >= 70:
        return "tier_2"
    return "tier_3"


def feature_vector_to_dict(sub_scores: list[SubScore]) -> dict[str, float]:
    """Flatten all sub-scores' contributing_features into one named
    feature vector. Used as fine-tuning input later. Naming convention:
    `{component}.{feature_key}`.
    """
    out: dict[str, float] = {}
    for ss in sub_scores:
        out[f"{ss.component}._value"] = ss.value
        for k, v in ss.contributing_features.items():
            out[f"{ss.component}.{k}"] = v
    return out

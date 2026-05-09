"""Psychology Evaluator — pure heuristic, no LLM, no external calls.

Implements framework §12 psychology_model checklist as a deterministic
function. No LLM call here means no agent_call_log row. The agent's
decisions are reproducible from inputs alone — perfect for backtests.

Inputs (from SetupContext.psychology_state):
- entry_planned_in_advance: bool
- invalidation_defined: bool
- position_size_predefined: bool
- setup_matches_playbook: bool
- fomo_entry: bool
- revenge_sizing: bool

Output: SubScore for `psychological_execution_quality` (0..1 flat,
0..5 in display weighted score).
"""

from __future__ import annotations

from macro_brain.types import SetupContext, SubScore


# Framework §12 — positive_execution_state requires ALL these true.
POSITIVE_FLAGS = (
    "entry_planned_in_advance",
    "invalidation_defined",
    "position_size_predefined",
    "setup_matches_playbook",
)

# Negative flags — ANY true triggers heavy penalty.
NEGATIVE_FLAGS = (
    "fomo_entry",
    "revenge_sizing",
)


def score_psychology_execution_quality(setup: SetupContext) -> SubScore:
    """Score the user's psychological execution state per framework §12.

    Mapping (flat 0..1):
    - All 4 positive flags true + zero negatives → 1.0
    - 3/4 positives + zero negatives → 0.75
    - 2/4 positives + zero negatives → 0.5
    - 1/4 positives + zero negatives → 0.25
    - 0 positives or any negative flag → 0.0

    Missing inputs default to "unknown" → counted as not-positive (i.e.,
    no credit) but not as negative (no penalty).
    """
    state = setup.psychology_state or {}

    # Treat invalidation_defined specially: pull from setup.stop_loss
    # if not explicitly set. The framework cares whether the trader has
    # a stop, regardless of where it's communicated.
    state_inv = state.get("invalidation_defined")
    if state_inv is None:
        state_inv = setup.stop_loss is not None

    positive_count = 0
    contributing: dict[str, float] = {}

    for flag in POSITIVE_FLAGS:
        v = state_inv if flag == "invalidation_defined" else state.get(flag)
        is_set = bool(v)
        contributing[flag] = 1.0 if is_set else 0.0
        if is_set:
            positive_count += 1

    has_negative = False
    for flag in NEGATIVE_FLAGS:
        v = bool(state.get(flag))
        contributing[flag] = 1.0 if v else 0.0
        if v:
            has_negative = True

    if has_negative:
        value = 0.0
        notes = "Negative execution state (FOMO or revenge sizing) — penalty applied."
    else:
        value = positive_count / len(POSITIVE_FLAGS)
        notes = f"{positive_count}/{len(POSITIVE_FLAGS)} positive execution flags."

    return SubScore(
        component="psychological_execution_quality",
        value=value,
        contributing_features=contributing,
        notes=notes,
    )

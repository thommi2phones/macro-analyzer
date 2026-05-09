"""Heuristic-call logging shim.

Today this is a passthrough — heuristic scorer calls do NOT write to
`agent_call_log` because that table is the LLM training corpus and
deterministic heuristic rows would pollute the (prompt, completion,
outcome) filter used for fine-tuning.

Every heuristic component's value + contributing features is already
persisted per-pass via `trade_scores` (column-per-component) and
`reasoning_trail.feature_vector` JSON, so attribution is preserved.

The wrapper exists so call sites are already in place: once a
`call_type` discriminator column lands on `agent_call_log` (or a
sibling `scorer_call_log` table is added), this module becomes the
real writer with zero scorer-code churn. See plan §"Proposed schema
evolution" and DECISIONS.md.
"""

from __future__ import annotations

from typing import Callable, TypeVar

T = TypeVar("T")


def with_log(
    *,
    agent_name: str,
    version: str,
    input_features: dict,
    fn: Callable[[], T],
) -> T:
    """Run `fn` and return its result. No DB write today.

    Args:
      agent_name: e.g. "volume_flow_confirmation"
      version: e.g. "volume_flow_confirmation@v1"
      input_features: serializable feature dict the heuristic consumed
      fn: zero-arg closure that returns the SubScore (or any value)

    The args are accepted now so call sites don't need to change when
    the writer slots in. They're intentionally unused.
    """
    _ = (agent_name, version, input_features)
    return fn()

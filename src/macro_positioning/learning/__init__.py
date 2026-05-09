"""Read/analytics side of the data flywheel.

Pure functions over a sqlite3.Connection. Each module turns raw rows
in `agent_call_log` / `source_outcomes` / `trade_scores` / `trades` /
`documents` / `prices` into surface-able signal for the dashboard.
"""

from __future__ import annotations

from macro_positioning.learning.mention_precision import mention_precision
from macro_positioning.learning.score_outcome_correlation import (
    score_outcome_correlation,
)
from macro_positioning.learning.source_attribution import (
    attribution,
    attribution_30d,
    attribution_90d,
    signal_attribution,
    signal_history,
)

__all__ = [
    "attribution",
    "attribution_30d",
    "attribution_90d",
    "signal_attribution",
    "signal_history",
    "score_outcome_correlation",
    "mention_precision",
]

"""Read/analytics side of the data flywheel.

Pure functions over a sqlite3.Connection. Each module turns raw rows
in `agent_call_log` / `source_outcomes` / `trade_scores` / `trades` /
`documents` / `prices` into surface-able signal for the dashboard.
"""

from __future__ import annotations

from macro_positioning.learning.author_calibration import (
    author_attribution,
    conviction_calibration,
)
from macro_positioning.learning.mention_precision import mention_precision
from macro_positioning.learning.model_version_writer import (
    backfill_model_versions,
    compose_model_version,
    version_stats,
)
from macro_positioning.learning.quality_scorer import (
    backfill_quality_scores,
    quality_summary,
)
from macro_positioning.learning.score_outcome_correlation import (
    score_outcome_correlation,
)
from macro_positioning.learning.source_attribution import (
    attribution,
    attribution_30d,
    attribution_90d,
    recommended_attribution_weights,
    signal_attribution,
    signal_history,
)

__all__ = [
    "attribution",
    "attribution_30d",
    "attribution_90d",
    "recommended_attribution_weights",
    "signal_attribution",
    "signal_history",
    "score_outcome_correlation",
    "mention_precision",
    "author_attribution",
    "conviction_calibration",
    "backfill_model_versions",
    "compose_model_version",
    "version_stats",
    "backfill_quality_scores",
    "quality_summary",
]

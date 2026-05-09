"""Freshness scoring for ingested documents.

Pure functions (no I/O). Take a published_at + source's freshness SLA,
return a 0..1 freshness score. Synthesis pipelines downweight stale
content; the dashboard shows freshness chips per source.

Design note (per docs/inputs_pipeline.md):
- A source's `freshness_sla_hours` is the half-life-equivalent: at the
  SLA hours mark, freshness == 0.5. Beyond 2× SLA, freshness == 0.
- Linear decay between [0, 2*SLA]. Deliberately simple — fancier curves
  (exponential, sigmoid) can come later if attribution data shows the
  decay shape matters.
- Sources without `freshness_sla_hours` (e.g., manual notes, chart
  uploads) are always treated as fresh (score == 1.0). They have no
  staleness model; the user is the freshness arbiter.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Iterable


def parse_iso8601(s: str) -> datetime:
    """Parse an ISO 8601 timestamp into a timezone-aware datetime.

    Accepts both 'Z' suffix and '+00:00' offset forms. Naive timestamps
    are assumed UTC.
    """
    if not s:
        raise ValueError("empty timestamp")
    cleaned = s.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def freshness_score(
    published_at: str | datetime,
    sla_hours: float | None,
    *,
    now: datetime | None = None,
) -> float:
    """Return a freshness score in [0.0, 1.0].

    - Fresh (just published): 1.0
    - At SLA hours: 0.5
    - At 2× SLA: 0.0 (and clamps to 0 beyond)
    - sla_hours None or <= 0 → always 1.0 (no staleness model)
    - Future-dated published_at → clamps to 1.0
    """
    if sla_hours is None or sla_hours <= 0:
        return 1.0
    pub = published_at if isinstance(published_at, datetime) else parse_iso8601(published_at)
    if pub.tzinfo is None:
        pub = pub.replace(tzinfo=UTC)
    current = now or datetime.now(UTC)
    elapsed_hours = (current - pub).total_seconds() / 3600.0
    if elapsed_hours <= 0:
        return 1.0
    # Linear: 1.0 at t=0, 0.5 at t=SLA, 0.0 at t=2*SLA
    score = 1.0 - (elapsed_hours / (2.0 * sla_hours))
    return max(0.0, min(1.0, score))


def freshness_label(score: float) -> str:
    """Human-readable bucket for a freshness score.

    Used in dashboard chips and CLI output.
    """
    if score >= 0.75:
        return "fresh"
    if score >= 0.5:
        return "recent"
    if score >= 0.25:
        return "stale"
    if score > 0.0:
        return "expiring"
    return "expired"


def is_stale(
    published_at: str | datetime,
    sla_hours: float | None,
    *,
    threshold: float = 0.25,
    now: datetime | None = None,
) -> bool:
    """Convenience: True if freshness is below `threshold` (default 0.25).

    Useful for filtering source health alerts and skipping ancient
    content from synthesis batches.
    """
    return freshness_score(published_at, sla_hours, now=now) < threshold


def average_freshness(
    timestamps: Iterable[str | datetime],
    sla_hours: float | None,
    *,
    now: datetime | None = None,
) -> float:
    """Mean freshness across a batch (e.g., the 10 most-recent docs from
    a source). Used in source health panel.
    """
    scores = [freshness_score(t, sla_hours, now=now) for t in timestamps]
    if not scores:
        return 0.0
    return sum(scores) / len(scores)

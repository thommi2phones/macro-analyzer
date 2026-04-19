"""Directional command center data collection.

Queries the database for theses, memos, and market observations,
then structures everything for the positioning command center UI.
Deduplicates theses by content so repeated pipeline runs don't bloat the view.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from macro_positioning.core.models import utc_now
from macro_positioning.core.settings import settings
from macro_positioning.db.repository import SQLiteRepository
from macro_positioning.db.schema import initialize_database


class ThesisSummary(BaseModel):
    thesis_id: str
    thesis: str
    theme: str
    direction: str
    confidence: float
    horizon: str
    assets: list[str] = Field(default_factory=list)
    status: str = "active"
    implied_positioning: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    extracted_at: str = ""
    run_count: int = 1  # how many times this thesis was extracted


class ThemeCluster(BaseModel):
    theme: str
    bullish: int = 0
    bearish: int = 0
    neutral: int = 0
    mixed: int = 0
    watchful: int = 0
    avg_confidence: float = 0.0
    top_assets: list[str] = Field(default_factory=list)
    dominant_direction: str = "neutral"


class CommandCenterSnapshot(BaseModel):
    generated_at: datetime = Field(default_factory=utc_now)
    # Memo
    memo_summary: str = ""
    consensus_views: list[str] = Field(default_factory=list)
    divergent_views: list[str] = Field(default_factory=list)
    suggested_positioning: list[str] = Field(default_factory=list)
    risks_to_watch: list[str] = Field(default_factory=list)
    expert_vs_market: list[str] = Field(default_factory=list)
    # Thesis breakdown (deduplicated)
    theses: list[ThesisSummary] = Field(default_factory=list)
    theme_clusters: list[ThemeCluster] = Field(default_factory=list)
    # Counts (deduplicated)
    unique_theses: int = 0
    bullish_count: int = 0
    bearish_count: int = 0
    neutral_count: int = 0
    avg_confidence: float = 0.0
    has_data: bool = False


def _deduplicate_theses(theses: list) -> list[tuple]:
    """Group theses by their text content, keep the most recent of each."""
    groups: dict[str, list] = defaultdict(list)
    for t in theses:
        groups[t.thesis.strip()].append(t)

    deduped = []
    for text, dupes in groups.items():
        # Keep the most recent extraction
        best = max(dupes, key=lambda t: t.extracted_at)
        deduped.append((best, len(dupes)))

    return deduped


def build_command_snapshot() -> CommandCenterSnapshot:
    initialize_database(settings.sqlite_path)
    repo = SQLiteRepository(settings.sqlite_path)

    snapshot = CommandCenterSnapshot()

    # Load latest memo
    memo = repo.latest_memo()
    if memo:
        snapshot.memo_summary = memo.summary
        snapshot.consensus_views = memo.consensus_views
        snapshot.divergent_views = memo.divergent_views
        snapshot.suggested_positioning = memo.suggested_positioning
        snapshot.risks_to_watch = memo.risks_to_watch
        snapshot.expert_vs_market = memo.expert_vs_market

    # Load and deduplicate theses
    raw_theses = repo.list_theses()
    if not raw_theses:
        return snapshot

    snapshot.has_data = True
    deduped = _deduplicate_theses(raw_theses)
    snapshot.unique_theses = len(deduped)

    thesis_summaries = []
    theme_map: dict[str, list] = defaultdict(list)

    for t, run_count in deduped:
        ts = ThesisSummary(
            thesis_id=t.thesis_id,
            thesis=t.thesis,
            theme=t.theme,
            direction=t.direction.value,
            confidence=t.confidence,
            horizon=t.horizon,
            assets=t.assets,
            status=t.status.value,
            implied_positioning=t.implied_positioning,
            risks=t.risks,
            extracted_at=t.extracted_at.isoformat() if t.extracted_at else "",
            run_count=run_count,
        )
        thesis_summaries.append(ts)
        theme_map[t.theme].append(t)

        if t.direction.value == "bullish":
            snapshot.bullish_count += 1
        elif t.direction.value == "bearish":
            snapshot.bearish_count += 1
        else:
            snapshot.neutral_count += 1

    snapshot.theses = sorted(thesis_summaries, key=lambda x: x.confidence, reverse=True)

    if deduped:
        snapshot.avg_confidence = sum(t.confidence for t, _ in deduped) / len(deduped)

    # Theme clusters
    for theme, items in theme_map.items():
        cluster = ThemeCluster(theme=theme)
        confs = []
        assets: set[str] = set()
        dir_counts: dict[str, int] = defaultdict(int)
        for t in items:
            dir_counts[t.direction.value] += 1
            confs.append(t.confidence)
            assets.update(t.assets)

        cluster.bullish = dir_counts.get("bullish", 0)
        cluster.bearish = dir_counts.get("bearish", 0)
        cluster.neutral = dir_counts.get("neutral", 0)
        cluster.mixed = dir_counts.get("mixed", 0)
        cluster.watchful = dir_counts.get("watchful", 0)
        cluster.avg_confidence = sum(confs) / len(confs) if confs else 0.0
        cluster.top_assets = sorted(assets)[:5]
        cluster.dominant_direction = max(dir_counts, key=dir_counts.get) if dir_counts else "neutral"
        snapshot.theme_clusters.append(cluster)

    snapshot.theme_clusters.sort(key=lambda c: c.avg_confidence, reverse=True)
    return snapshot

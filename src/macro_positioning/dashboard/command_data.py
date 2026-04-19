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


class AssetBreakdown(BaseModel):
    """Per-asset aggregation across all theses that mention it."""
    asset: str
    dominant_direction: str = "neutral"    # bullish|bearish|neutral|mixed|watchful
    confidence: float = 0.0                # conviction score 0..1
    thesis_count: int = 0
    themes: list[str] = Field(default_factory=list)


class TacticalAnnotation(BaseModel):
    """Inline tactical state for a signal — what the tactical side is
    currently doing on this symbol. Optional, None when tactical unreachable.
    """
    active_setups: int = 0
    at_entry: int = 0
    in_trade: int = 0
    blocked_by_gate: int = 0
    latest_stage: str = ""


class ActionableSignal(BaseModel):
    """One entry in the top-hero 'Actionable Signals' section.

    Grouped by side (LONG/SHORT/WATCH), per asset, with the strongest
    rationale and the tactical state reacting to it inline.
    """
    side: str                              # LONG | SHORT | WATCH
    asset: str
    theme: str = ""
    conviction: float = 0.0                # aggregated confidence
    horizon: str = ""
    rationale: str = ""
    source_thesis_ids: list[str] = Field(default_factory=list)
    tactical: TacticalAnnotation | None = None


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
    # Per-asset breakdown (drill-down below themes)
    asset_breakdown: list[AssetBreakdown] = Field(default_factory=list)
    # Top actionable signals (hero section on /positioning)
    actionable_signals: list[ActionableSignal] = Field(default_factory=list)
    tactical_reachable: bool = False
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

    # Per-asset breakdown (aggregate all deduped theses by asset)
    snapshot.asset_breakdown = build_asset_breakdown([t for t, _ in deduped])

    # Actionable signals — top hero section
    try:
        from macro_positioning.integration import tactical_client
        tactical_snapshot = tactical_client.fetch_tactical_snapshot()
        snapshot.tactical_reachable = bool(
            tactical_snapshot.get("configured") and tactical_snapshot.get("events") is not None
        )
        tactical_events = tactical_snapshot.get("events") or []
    except Exception:
        tactical_events = []
        snapshot.tactical_reachable = False

    snapshot.actionable_signals = build_actionable_signals(
        theses=[t for t, _ in deduped],
        tactical_events=tactical_events,
    )

    return snapshot


# ---------------------------------------------------------------------------
# Asset breakdown + actionable signals
# ---------------------------------------------------------------------------

# Direction → side mapping for the hero section
_DIRECTION_TO_SIDE = {
    "bullish": "LONG",
    "bearish": "SHORT",
    "watchful": "WATCH",
    "mixed": "WATCH",
    "neutral": "WATCH",
}


def build_asset_breakdown(theses: list) -> list[AssetBreakdown]:
    """Aggregate theses by individual asset (not theme).

    Each thesis contributes to every asset in its `assets` list. Direction
    is weight-averaged by confidence. This powers the per-asset drilldown
    below the theme heatmap.
    """
    by_asset: dict[str, dict] = defaultdict(
        lambda: {"dir_weights": defaultdict(float), "themes": set(), "count": 0}
    )

    for t in theses:
        assets = t.assets or []
        if not assets:
            continue
        direction = t.direction.value if hasattr(t.direction, "value") else str(t.direction)
        for asset in assets:
            key = asset.strip().lower()
            if not key:
                continue
            entry = by_asset[key]
            entry["dir_weights"][direction] += t.confidence
            entry["themes"].add(t.theme)
            entry["count"] += 1

    breakdowns: list[AssetBreakdown] = []
    for asset, data in by_asset.items():
        dir_weights = data["dir_weights"]
        if not dir_weights:
            continue
        dominant = max(dir_weights, key=dir_weights.get)
        total = sum(dir_weights.values())
        conviction = dir_weights[dominant] / total if total else 0.0
        breakdowns.append(AssetBreakdown(
            asset=asset,
            dominant_direction=dominant,
            confidence=round(conviction, 3),
            thesis_count=data["count"],
            themes=sorted(data["themes"]),
        ))

    breakdowns.sort(key=lambda b: -b.confidence)
    return breakdowns


def _summarize_tactical_for_symbol(symbol: str, tactical_events: list) -> TacticalAnnotation | None:
    """Scan tactical event feed for setups matching this symbol and summarize."""
    if not tactical_events or not symbol:
        return None

    sym = symbol.upper().strip()
    active_setups = 0
    at_entry = 0
    in_trade = 0
    blocked = 0
    latest_stage = ""

    # Tactical events are newest-first typically; iterate all to aggregate
    # Deduplicate by setup_id — only count each setup once (the most recent state)
    seen_setups: dict[str, str] = {}
    for ev in tactical_events:
        payload = ev.get("payload") if isinstance(ev, dict) else None
        if not isinstance(payload, dict):
            continue
        ev_symbol = (payload.get("symbol") or "").upper().strip()
        if ev_symbol != sym:
            continue
        setup_id = payload.get("setup_id") or ""
        stage = (payload.get("setup_stage") or "").lower()
        if setup_id and setup_id not in seen_setups:
            seen_setups[setup_id] = stage

    if not seen_setups:
        return None

    for _, stage in seen_setups.items():
        active_setups += 1
        if stage == "trigger":
            at_entry += 1
        elif stage == "in_trade":
            in_trade += 1
        if not latest_stage:
            latest_stage = stage

    return TacticalAnnotation(
        active_setups=active_setups,
        at_entry=at_entry,
        in_trade=in_trade,
        blocked_by_gate=blocked,
        latest_stage=latest_stage,
    )


def build_actionable_signals(
    theses: list,
    tactical_events: list | None = None,
) -> list[ActionableSignal]:
    """Derive top actionable signals for the hero section.

    Group by (side, asset), aggregate by confidence. Each asset shows up
    once per side with the strongest supporting thesis. Tactical state
    is annotated inline when the tactical-executor is reachable.
    """
    tactical_events = tactical_events or []

    # (side, asset) -> {conviction, horizon, theme, rationale, thesis_ids}
    bucket: dict[tuple[str, str], dict] = defaultdict(lambda: {
        "conviction": 0.0,
        "thesis_ids": [],
        "themes": set(),
        "horizon": "",
        "rationale": "",
        "best_confidence": 0.0,
    })

    for t in theses:
        direction = t.direction.value if hasattr(t.direction, "value") else str(t.direction)
        side = _DIRECTION_TO_SIDE.get(direction)
        if side is None:
            continue

        assets = t.assets or []
        if not assets:
            continue

        for asset in assets:
            key = asset.strip().lower()
            if not key:
                continue
            b = bucket[(side, key)]
            b["conviction"] += t.confidence
            b["thesis_ids"].append(t.thesis_id)
            b["themes"].add(t.theme)
            if t.confidence > b["best_confidence"]:
                b["best_confidence"] = t.confidence
                b["horizon"] = t.horizon
                b["rationale"] = (t.thesis or "").strip()[:220]

    signals: list[ActionableSignal] = []
    for (side, asset), data in bucket.items():
        # Normalize conviction to 0..1 (simple squashing)
        conviction = min(1.0, data["conviction"] / 3.0) if data["conviction"] else 0.0
        themes_list = sorted(data["themes"])
        primary_theme = themes_list[0] if themes_list else ""
        signals.append(ActionableSignal(
            side=side,
            asset=asset,
            theme=primary_theme,
            conviction=round(conviction, 3),
            horizon=data["horizon"],
            rationale=data["rationale"],
            source_thesis_ids=data["thesis_ids"][:5],
            tactical=_summarize_tactical_for_symbol(asset, tactical_events),
        ))

    # Order: LONG first, then SHORT, then WATCH. Within each, by conviction desc.
    side_order = {"LONG": 0, "SHORT": 1, "WATCH": 2}
    signals.sort(key=lambda s: (side_order.get(s.side, 9), -s.conviction))
    return signals

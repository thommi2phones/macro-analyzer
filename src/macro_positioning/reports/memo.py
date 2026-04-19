from __future__ import annotations

import hashlib
from collections import Counter, defaultdict

from macro_positioning.core.models import (
    PositioningMemo,
    PositioningRecommendation,
    Thesis,
    ValidatedThesis,
    ViewDirection,
)


def build_positioning_memo(
    theses: list[Thesis],
    validated_theses: list[ValidatedThesis] | None = None,
    recommendations: list[PositioningRecommendation] | None = None,
    required_inputs: list[str] | None = None,
    source_weights: dict[str, float] | None = None,
) -> PositioningMemo:
    validated_theses = validated_theses or []
    recommendations = recommendations or []
    source_weights = source_weights or {}

    sorted_theses = sorted(
        theses,
        key=lambda item: (item.confidence, item.freshness_score),
        reverse=True,
    )
    consensus_views = summarize_consensus(sorted_theses, source_weights)
    divergent_views = summarize_divergence(sorted_theses)
    suggestions = summarize_positioning(sorted_theses, recommendations)
    risks = summarize_risks(sorted_theses)
    validation_summary = summarize_validation(validated_theses)
    expert_vs_market = summarize_expert_vs_market(validated_theses)
    summary = build_summary(consensus_views, divergent_views, suggestions, validated_theses)
    memo_id = hashlib.sha1(summary.encode("utf-8")).hexdigest()[:16]
    return PositioningMemo(
        memo_id=memo_id,
        title="Macro Positioning Memo",
        summary=summary,
        consensus_views=consensus_views,
        divergent_views=divergent_views,
        suggested_positioning=suggestions,
        risks_to_watch=risks,
        thesis_ids=[thesis.thesis_id for thesis in sorted_theses],
        validation_summary=validation_summary,
        expert_vs_market=expert_vs_market,
        required_inputs=required_inputs or [],
    )


def _source_weight(source_id: str, weights: dict[str, float]) -> float:
    return weights.get(source_id, 0.5)


def summarize_consensus(
    theses: list[Thesis],
    source_weights: dict[str, float] | None = None,
) -> list[str]:
    source_weights = source_weights or {}
    grouped: dict[str, list[Thesis]] = defaultdict(list)
    for thesis in theses:
        grouped[thesis.theme].append(thesis)

    consensus: list[str] = []
    for theme, items in grouped.items():
        # Sum trust-weighted votes per direction
        direction_weight: dict[ViewDirection, float] = defaultdict(float)
        distinct_sources: set[str] = set()
        for thesis in items:
            w = max(
                _source_weight(sid, source_weights) for sid in thesis.source_ids
            ) if thesis.source_ids else 0.5
            direction_weight[thesis.direction] += w * thesis.confidence
            distinct_sources.update(thesis.source_ids)
        if not direction_weight:
            continue
        top_direction, top_weight = max(direction_weight.items(), key=lambda kv: kv[1])
        total_weight = sum(direction_weight.values())
        share = top_weight / total_weight if total_weight else 0.0
        if share < 0.5:
            # Not really a consensus for this theme
            continue
        top_assets = sorted({a for t in items for a in t.assets})[:3]
        source_tag = f" across {len(distinct_sources)} sources" if len(distinct_sources) > 1 else ""
        assets_tag = f" (focus: {', '.join(top_assets)})" if top_assets else ""
        consensus.append(
            f"{theme.title()}: {top_direction.value} bias ({share:.0%} of weighted votes"
            f"{source_tag}){assets_tag}."
        )
    # Rank: themes with stronger share first
    consensus.sort(key=lambda s: -float(s.split("(")[1].split("%")[0]) if "(" in s else 0)
    return consensus[:6]


def summarize_divergence(theses: list[Thesis]) -> list[str]:
    grouped: dict[str, list[Thesis]] = defaultdict(list)
    for thesis in theses:
        grouped[thesis.theme].append(thesis)
    divergences: list[str] = []
    for theme, items in grouped.items():
        directions = {t.direction for t in items}
        # Only real disagreement counts - watchful + directional is normal
        strong = {d for d in directions if d in (ViewDirection.bullish, ViewDirection.bearish)}
        if len(strong) > 1:
            sources = sorted({sid for t in items for sid in t.source_ids})
            divergences.append(
                f"{theme.title()}: split between {', '.join(sorted(d.value for d in strong))} "
                f"across {len(sources)} source(s)."
            )
    return divergences[:5]


def summarize_positioning(
    theses: list[Thesis],
    recommendations: list[PositioningRecommendation],
) -> list[str]:
    if recommendations:
        return [
            f"{item.title} (horizon {item.horizon}, conf {item.confidence:.2f}): "
            f"{', '.join(item.expression) or item.rationale}"
            for item in recommendations[:6]
        ]
    suggestions: list[str] = []
    for thesis in theses[:5]:
        suggestions.extend(thesis.implied_positioning[:2])
    unique: list[str] = []
    seen: set[str] = set()
    for suggestion in suggestions:
        if suggestion in seen:
            continue
        seen.add(suggestion)
        unique.append(suggestion)
    return unique[:6]


def summarize_risks(theses: list[Thesis]) -> list[str]:
    risks = [risk for thesis in theses for risk in thesis.risks]
    unique: list[str] = []
    seen: set[str] = set()
    for risk in risks:
        if risk in seen:
            continue
        seen.add(risk)
        unique.append(risk)
    return unique[:6]


def summarize_validation(validated_theses: list[ValidatedThesis]) -> list[str]:
    # Sort by support descending so strongest-confirmed views lead
    ranked = sorted(
        validated_theses,
        key=lambda v: v.validation.support_score,
        reverse=True,
    )
    return [
        f"{item.thesis.theme.title()} [{item.thesis.direction.value}]: "
        f"support {item.validation.support_score:.2f}, market is "
        f"{item.validation.sentiment_alignment}."
        for item in ranked[:6]
    ]


def summarize_expert_vs_market(validated_theses: list[ValidatedThesis]) -> list[str]:
    rows: list[str] = []
    for item in validated_theses:
        thesis = item.thesis
        v = item.validation
        alignment = v.sentiment_alignment
        # Highlight gaps: expert directional but market contradictory/unknown
        tag = ""
        if alignment == "contradictory":
            tag = " ← MARKET DISAGREES"
        elif alignment == "unknown":
            tag = " ← no market signal yet"
        rows.append(
            f"[{thesis.theme}] expert={thesis.direction.value}, market={alignment}, "
            f"support={v.support_score:.2f}{tag}"
        )
    return rows[:8]


def build_summary(
    consensus: list[str],
    divergence: list[str],
    suggestions: list[str],
    validated: list[ValidatedThesis],
) -> str:
    parts: list[str] = []
    if consensus:
        parts.append(f"Leading consensus → {consensus[0]}")
    contradicted = [
        v for v in validated if v.validation.sentiment_alignment == "contradictory"
    ]
    if contradicted:
        parts.append(
            f"{len(contradicted)} thesis(es) flagged where market disagrees with expert view."
        )
    if divergence:
        parts.append(f"Main disagreement: {divergence[0]}")
    if suggestions:
        parts.append(f"Top expression → {suggestions[0]}")
    return " | ".join(parts) if parts else "No active theses available."

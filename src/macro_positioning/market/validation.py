from __future__ import annotations

import hashlib

from macro_positioning.core.models import (
    MarketObservation,
    MarketValidation,
    PositioningRecommendation,
    Thesis,
    ValidatedThesis,
    ViewDirection,
)


# ---------------------------------------------------------------------------
# Observation polarity inference
# ---------------------------------------------------------------------------

# Phrases in an observation's `interpretation` that suggest a bullish read
# for the associated market/theme.
POSITIVE_MARKERS = (
    "support", "bullish", "strong", "expanding", "improving",
    "accelerat", "breakout", "resilient", "favours", "favors", "tailwind",
    "loosening", "easing", "stabilising", "stabilizing", "confirming",
    "positive", "rising", "upside", "tight labor", "cooling",
)
NEGATIVE_MARKERS = (
    "bearish", "weak", "weakening", "deteriorat", "decelerat", "rolling over",
    "fatigue", "tightening conditions", "restrictive", "strain", "stress",
    "contraction", "contracting", "negative", "drag", "downside", "overbought",
    "breakdown", "slowing",
)


def observation_polarity(obs: MarketObservation) -> int:
    """Return +1 (bullish), -1 (bearish), or 0 (neutral / unknown) for an observation."""
    text = " ".join(filter(None, [obs.interpretation, obs.metric, str(obs.value)])).lower()
    pos = sum(1 for m in POSITIVE_MARKERS if m in text)
    neg = sum(1 for m in NEGATIVE_MARKERS if m in text)
    if pos and neg:
        return 0
    if pos:
        return 1
    if neg:
        return -1
    return 0


def _matches_thesis(obs: MarketObservation, thesis: Thesis) -> bool:
    """Match observation to thesis by asset or theme overlap."""
    targets = set(thesis.assets) | {thesis.theme}
    # Canonical alias expansion so "growth" thesis picks up "labor"/"consumer" obs
    aliases = {
        "growth": {"growth", "labor", "consumer", "housing"},
        "inflation": {"inflation", "rates"},
        "policy": {"policy", "rates", "financial_conditions"},
        "liquidity": {"liquidity", "financial_conditions", "rates"},
        "rates": {"rates", "financial_conditions"},
        "credit": {"credit", "financial_conditions"},
        "usd": {"usd", "fx"},
    }
    expanded = set(targets)
    for target in targets:
        expanded |= aliases.get(target, set())
    return obs.market in expanded or obs.metric.lower() in expanded


class ThesisValidator:
    def validate(self, thesis: Thesis, observations: list[MarketObservation]) -> MarketValidation:
        relevant = [o for o in observations if _matches_thesis(o, thesis)]
        expert_polarity = _thesis_polarity(thesis)

        if not relevant:
            return MarketValidation(
                thesis_id=thesis.thesis_id,
                support_score=_prior_only_score(thesis),
                sentiment_alignment="unknown",
                cross_asset_confirmation=[],
                notes=["No market observations matched this thesis' assets/theme."],
                observations=[],
            )

        agree = 0
        disagree = 0
        neutral = 0
        for obs in relevant:
            pol = observation_polarity(obs)
            if pol == 0 or expert_polarity == 0:
                neutral += 1
            elif pol == expert_polarity:
                agree += 1
            else:
                disagree += 1

        scored = agree - disagree
        directional = agree + disagree
        if directional == 0:
            alignment = "unknown"
            agreement_ratio = 0.0
        else:
            agreement_ratio = scored / directional
            if agreement_ratio >= 0.5:
                alignment = "supportive"
            elif agreement_ratio <= -0.5:
                alignment = "contradictory"
            else:
                alignment = "mixed"

        # Support score blends expert confidence with agreement signal.
        # Starts from confidence, nudges toward 1.0 on agreement and toward
        # the floor on disagreement; neutrals have no effect.
        support_score = thesis.confidence
        if directional:
            support_score = _blend(thesis.confidence, 0.5 + 0.5 * agreement_ratio, weight=0.55)
        if thesis.direction in (ViewDirection.mixed, ViewDirection.watchful):
            support_score -= 0.05
        support_score = max(0.10, min(0.97, support_score))

        notes = [
            f"Market alignment is {alignment} for {thesis.theme}: "
            f"{agree} confirming, {disagree} contradicting, {neutral} neutral obs."
        ]
        notes.extend(_observation_note(o) for o in relevant[:4])

        return MarketValidation(
            thesis_id=thesis.thesis_id,
            support_score=support_score,
            sentiment_alignment=alignment,
            cross_asset_confirmation=[
                (o.interpretation or f"{o.market}: {o.metric}") for o in relevant[:3]
            ],
            notes=notes,
            observations=relevant[:5],
        )


def _thesis_polarity(thesis: Thesis) -> int:
    if thesis.direction == ViewDirection.bullish:
        return 1
    if thesis.direction == ViewDirection.bearish:
        return -1
    return 0


def _blend(a: float, b: float, weight: float) -> float:
    """Weighted average: weight on b, (1-weight) on a."""
    return (1.0 - weight) * a + weight * b


def _prior_only_score(thesis: Thesis) -> float:
    score = thesis.confidence * 0.65
    if thesis.direction == ViewDirection.mixed:
        score -= 0.06
    if thesis.direction == ViewDirection.watchful:
        score -= 0.04
    return max(0.10, min(0.85, score))


def _observation_note(obs: MarketObservation) -> str:
    base = f"{obs.market}/{obs.metric} = {obs.value}"
    if obs.interpretation:
        return f"{base} — {obs.interpretation}"
    return base


def validate_theses(
    theses: list[Thesis], observations: list[MarketObservation]
) -> list[ValidatedThesis]:
    validator = ThesisValidator()
    return [
        ValidatedThesis(thesis=thesis, validation=validator.validate(thesis, observations))
        for thesis in theses
    ]


def build_recommendations(
    validated_theses: list[ValidatedThesis],
    min_support: float = 0.55,
) -> list[PositioningRecommendation]:
    recommendations: list[PositioningRecommendation] = []
    for item in validated_theses:
        thesis = item.thesis
        validation = item.validation
        if validation.support_score < min_support:
            continue
        if validation.sentiment_alignment == "contradictory":
            continue  # market is actively against us — don't promote
        title = f"{thesis.theme.title()} {thesis.direction.value} setup"
        rationale = (
            f"Expert view is {thesis.direction.value} with {validation.sentiment_alignment} "
            f"market confirmation (support score {validation.support_score:.2f})."
        )
        recommendations.append(
            PositioningRecommendation(
                recommendation_id=hashlib.sha1(
                    f"{thesis.thesis_id}|{title}".encode("utf-8")
                ).hexdigest()[:16],
                title=title,
                rationale=rationale,
                horizon=thesis.horizon,
                expression=thesis.implied_positioning,
                confidence=min((thesis.confidence + validation.support_score) / 2, 0.95),
                linked_thesis_ids=[thesis.thesis_id],
                risks=thesis.risks[:3],
            )
        )
    # Rank by confidence descending so top picks lead the memo
    recommendations.sort(key=lambda r: r.confidence, reverse=True)
    return recommendations

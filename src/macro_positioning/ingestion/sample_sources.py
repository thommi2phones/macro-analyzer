from __future__ import annotations

from datetime import UTC, datetime, timedelta

import hashlib

from macro_positioning.core.models import MarketObservation, PipelineContext, RawDocument


def sample_documents() -> list[RawDocument]:
    now = datetime.now(UTC)
    return [
        RawDocument(
            source_id="macro_kol_001",
            title="Disinflation is progressing but growth is rolling over",
            url="https://example.com/disinflation-growth",
            published_at=now - timedelta(days=2),
            author="Example Analyst",
            content_type="article",
            tags=["inflation", "growth", "rates"],
            raw_text=(
                "We think US growth is slowing faster than consensus while inflation continues to ease. "
                "That should be supportive for duration over the next one to three months, although a sharp "
                "energy rebound is the clearest upside risk to this view."
            ),
        ),
        RawDocument(
            source_id="macro_kol_002",
            title="Podcast transcript: dollar fatigue and commodity resilience",
            url="https://example.com/dollar-fatigue",
            published_at=now - timedelta(days=1),
            author="Example Host",
            content_type="transcript",
            tags=["usd", "commodities", "macro"],
            raw_text=(
                "Our base case is that the dollar loses momentum over the coming quarter as global growth "
                "stabilizes. We prefer selective commodity exposure and think gold still works if real yields "
                "stop rising. The risk is that financial conditions tighten again."
            ),
        ),
        RawDocument(
            source_id="macro_kol_003",
            title="Tactical note: equity breadth improving under the surface",
            url="https://example.com/equity-breadth",
            published_at=now - timedelta(hours=12),
            author="Example Strategist",
            content_type="note",
            tags=["equities", "breadth", "risk-assets"],
            raw_text=(
                "Breadth is improving and cyclical leadership is expanding, which is modestly bullish for equities "
                "over the next several weeks. We would stay tactical because a deterioration in labor data would "
                "change the setup quickly."
            ),
        ),
    ]


def sample_context() -> PipelineContext:
    now = datetime.now(UTC)
    observations = [
        MarketObservation(
            observation_id=observation_id_for("rates", "10y_real_yield"),
            market="rates",
            metric="10y_real_yield",
            value="-12 bps WoW",
            as_of=now,
            interpretation="Falling real yields support duration and gold.",
            source="sample-market-feed",
        ),
        MarketObservation(
            observation_id=observation_id_for("usd", "dxy_momentum"),
            market="usd",
            metric="dxy_momentum",
            value="negative over 20 sessions",
            as_of=now,
            interpretation="Dollar momentum is weakening.",
            source="sample-market-feed",
        ),
        MarketObservation(
            observation_id=observation_id_for("equities", "breadth"),
            market="equities",
            metric="breadth",
            value="61% above 50dma",
            as_of=now,
            interpretation="Breadth improvement is confirming cyclical participation.",
            source="sample-market-feed",
        ),
    ]
    return PipelineContext(
        market_observations=observations,
        analyst_notes=["Sample context only. Replace with real validation feeds before production use."],
    )


def observation_id_for(market: str, metric: str) -> str:
    return hashlib.sha1(f"{market}|{metric}".encode("utf-8")).hexdigest()[:16]

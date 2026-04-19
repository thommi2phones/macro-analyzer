from __future__ import annotations

from collections.abc import Iterable

from macro_positioning.core.models import MarketObservation, Thesis


class MarketDataProvider:
    provider_name = "base"

    def gather(self, theses: list[Thesis]) -> list[MarketObservation]:
        raise NotImplementedError


class StaticMarketDataProvider(MarketDataProvider):
    provider_name = "static"

    def __init__(self, observations: Iterable[MarketObservation] | None = None) -> None:
        self.observations = list(observations or [])

    def gather(self, theses: list[Thesis]) -> list[MarketObservation]:
        return list(self.observations)

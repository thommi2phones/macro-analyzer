from __future__ import annotations

from collections.abc import Iterable

from macro_positioning.core.models import RawDocument, SourceDefinition


class SourceConnector:
    connector_type = "base"

    def supports(self, source: SourceDefinition) -> bool:
        raise NotImplementedError

    def fetch(self, source: SourceDefinition) -> list[RawDocument]:
        raise NotImplementedError


class ManualSourceConnector(SourceConnector):
    connector_type = "manual"

    def supports(self, source: SourceDefinition) -> bool:
        return source.source_type.value == "manual"

    def fetch(self, source: SourceDefinition) -> list[RawDocument]:
        return []


class ConnectorRegistry:
    def __init__(self, connectors: Iterable[SourceConnector] | None = None) -> None:
        self.connectors = list(connectors or [ManualSourceConnector()])

    def connector_for(self, source: SourceDefinition) -> SourceConnector | None:
        for connector in self.connectors:
            if connector.supports(source):
                return connector
        return None

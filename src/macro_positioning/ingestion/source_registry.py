from __future__ import annotations

import json
from pathlib import Path

from macro_positioning.core.models import SourceDefinition


def load_source_registry(path: Path) -> list[SourceDefinition]:
    payload = json.loads(path.read_text())
    return [SourceDefinition.model_validate(item) for item in payload]


def source_trust_weights(sources: list[SourceDefinition]) -> dict[str, float]:
    """Map source_id -> trust_weight for use in weighted consensus."""
    return {s.source_id: s.trust_weight for s in sources}

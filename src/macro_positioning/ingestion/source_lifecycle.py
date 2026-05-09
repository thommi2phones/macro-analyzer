"""Source lifecycle: add/promote/archive/list operations on config/sources.json.

config/sources.json is the canonical registry. Existing legacy files
(newsletter_sources.json, sources.example.json) remain readable but are
not the source of truth here.

Per docs/inputs_pipeline.md, the lifecycle is:
1. discovery → 2. onboarding → 3. normalization → 4. dedup
→ 5. pre-tagging → 6. freshness scoring → 7. outcome attribution
→ 8. fine-tuning → 9. offboarding (archive, never delete)

This module handles 2 and 9 directly, and provides query helpers used by
the dashboard and CLI.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Iterable, Literal

from pydantic import BaseModel, Field, ConfigDict

from macro_positioning.core.settings import settings


SOURCES_PATH = settings.base_dir / "config" / "sources.json"


# ---------------------------------------------------------------------------
# Models — flexible to absorb extra fields without breaking older configs.
# ---------------------------------------------------------------------------

Priority = Literal["core", "secondary", "trial", "archived"]
SourceType = Literal[
    "newsletter", "podcast", "rss", "api", "gmail", "manual_notes", "chart"
]


class SourceChannel(BaseModel):
    model_config = ConfigDict(extra="allow")
    channel_type: str
    label: str = ""
    url: str = ""


class SourceRecord(BaseModel):
    """One row from sources.json. Tolerant of extra fields so future config
    schema versions don't break us."""

    model_config = ConfigDict(extra="allow")

    source_id: str
    name: str
    source_type: str
    author: str = ""
    priority: str = "trial"
    trust_weight: float = 0.5
    market_focus: list[str] = Field(default_factory=list)
    routing_tags: list[str] = Field(default_factory=list)
    fetch_cadence: str = "manual"
    freshness_sla_hours: int | None = None
    transcription_mode: str | None = None
    research_style: str = ""
    validation_focus: list[str] = Field(default_factory=list)
    channels: list[SourceChannel] = Field(default_factory=list)
    onboarded_at: str | None = None
    archived_at: str | None = None


# ---------------------------------------------------------------------------
# Read / write the canonical registry
# ---------------------------------------------------------------------------

def _load_raw() -> dict:
    if not SOURCES_PATH.exists():
        return {"$schema_version": "1.0", "sources": []}
    return json.loads(SOURCES_PATH.read_text())


def _save_raw(data: dict) -> None:
    SOURCES_PATH.parent.mkdir(parents=True, exist_ok=True)
    SOURCES_PATH.write_text(json.dumps(data, indent=2) + "\n")


def load_sources(*, include_archived: bool = False) -> list[SourceRecord]:
    """Return all sources from config/sources.json.

    By default, archived sources are filtered out (they're kept for
    historical attribution but irrelevant to current ingestion).
    """
    raw = _load_raw()
    out: list[SourceRecord] = []
    for entry in raw.get("sources", []):
        rec = SourceRecord.model_validate(entry)
        if not include_archived and rec.archived_at:
            continue
        out.append(rec)
    return out


def get_source(source_id: str) -> SourceRecord | None:
    """Lookup a single source by id (returns archived too)."""
    for rec in load_sources(include_archived=True):
        if rec.source_id == source_id:
            return rec
    return None


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------

def _today_iso() -> str:
    return date.today().isoformat()


def add_source(
    source_id: str,
    *,
    name: str,
    source_type: str,
    author: str = "",
    priority: str = "trial",
    trust_weight: float = 0.5,
    market_focus: list[str] | None = None,
    routing_tags: list[str] | None = None,
    fetch_cadence: str = "manual",
    freshness_sla_hours: int | None = None,
    research_style: str = "",
    validation_focus: list[str] | None = None,
    channels: list[dict] | None = None,
) -> SourceRecord:
    """Onboard a new source. Raises ValueError if source_id already exists.

    Defaults reflect the inputs_pipeline spec: trial priority, 0.5 trust,
    until evidence justifies promotion.
    """
    raw = _load_raw()
    existing_ids = {s["source_id"] for s in raw.get("sources", [])}
    if source_id in existing_ids:
        raise ValueError(f"Source {source_id!r} already exists")

    record = SourceRecord(
        source_id=source_id,
        name=name,
        source_type=source_type,
        author=author,
        priority=priority,
        trust_weight=trust_weight,
        market_focus=market_focus or [],
        routing_tags=routing_tags or [],
        fetch_cadence=fetch_cadence,
        freshness_sla_hours=freshness_sla_hours,
        research_style=research_style,
        validation_focus=validation_focus or [],
        channels=[SourceChannel.model_validate(c) for c in (channels or [])],
        onboarded_at=_today_iso(),
        archived_at=None,
    )
    raw.setdefault("sources", []).append(record.model_dump(exclude_none=True))
    _save_raw(raw)
    return record


def archive_source(source_id: str) -> SourceRecord:
    """Archive a source. Sets archived_at and priority='archived'.
    Does NOT delete — historical attribution depends on the record
    remaining in the registry. Idempotent.
    """
    raw = _load_raw()
    for entry in raw.get("sources", []):
        if entry["source_id"] == source_id:
            entry["archived_at"] = _today_iso()
            entry["priority"] = "archived"
            _save_raw(raw)
            return SourceRecord.model_validate(entry)
    raise KeyError(f"Source {source_id!r} not found")


def unarchive_source(source_id: str, new_priority: str = "trial") -> SourceRecord:
    """Reverse an archive. Clears archived_at; resets priority."""
    raw = _load_raw()
    for entry in raw.get("sources", []):
        if entry["source_id"] == source_id:
            entry["archived_at"] = None
            entry["priority"] = new_priority
            _save_raw(raw)
            return SourceRecord.model_validate(entry)
    raise KeyError(f"Source {source_id!r} not found")


def promote_source(
    source_id: str,
    new_priority: str,
) -> SourceRecord:
    """Change a source's priority (e.g., 'trial' → 'secondary' → 'core').
    Use this when ≥30 days of evidence justifies the bump.
    """
    valid = {"core", "secondary", "trial", "archived"}
    if new_priority not in valid:
        raise ValueError(f"Invalid priority {new_priority!r}; expected one of {valid}")
    raw = _load_raw()
    for entry in raw.get("sources", []):
        if entry["source_id"] == source_id:
            entry["priority"] = new_priority
            if new_priority == "archived":
                entry["archived_at"] = _today_iso()
            elif entry.get("archived_at"):
                # Promoting out of archived state implicitly clears the date.
                entry["archived_at"] = None
            _save_raw(raw)
            return SourceRecord.model_validate(entry)
    raise KeyError(f"Source {source_id!r} not found")


def retag_source(
    source_id: str,
    *,
    add: Iterable[str] | None = None,
    remove: Iterable[str] | None = None,
) -> SourceRecord:
    """Adjust a source's routing_tags (additive + subtractive)."""
    raw = _load_raw()
    for entry in raw.get("sources", []):
        if entry["source_id"] == source_id:
            current = set(entry.get("routing_tags", []))
            if add:
                current |= set(add)
            if remove:
                current -= set(remove)
            entry["routing_tags"] = sorted(current)
            _save_raw(raw)
            return SourceRecord.model_validate(entry)
    raise KeyError(f"Source {source_id!r} not found")


# ---------------------------------------------------------------------------
# Aggregations for dashboard / CLI display
# ---------------------------------------------------------------------------

class SourceSummary(BaseModel):
    """Compact source view for tables and chips."""
    source_id: str
    name: str
    source_type: str
    priority: str
    trust_weight: float
    routing_tags: list[str]
    onboarded_at: str | None
    archived_at: str | None


def summarize_sources(*, include_archived: bool = False) -> list[SourceSummary]:
    return [
        SourceSummary(
            source_id=r.source_id,
            name=r.name,
            source_type=r.source_type,
            priority=r.priority,
            trust_weight=r.trust_weight,
            routing_tags=r.routing_tags,
            onboarded_at=r.onboarded_at,
            archived_at=r.archived_at,
        )
        for r in load_sources(include_archived=include_archived)
    ]


def count_by_priority() -> dict[str, int]:
    """Counts of {core, secondary, trial, archived}. Includes archived."""
    out: dict[str, int] = {}
    for r in load_sources(include_archived=True):
        out[r.priority] = out.get(r.priority, 0) + 1
    return out

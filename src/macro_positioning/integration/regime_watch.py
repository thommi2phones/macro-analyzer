"""Regime change detection + webhook push to tactical-executor.

When the brain's regime assessment shifts meaningfully (e.g., bullish →
bearish on a theme, or overall regime changes), fire a webhook to the
tactical side so it can re-evaluate active setups.

Two modes:
  1. Polling — tactical periodically GETs /positioning/regime
  2. Push — macro detects change and POSTs to a tactical webhook URL

This module implements mode 2 (optional, for real-time alerts).

TODO(stream-d):
  - Store last-known regime snapshot in DB
  - Run detect_regime_change() after every pipeline run
  - If delta exceeds threshold, POST to settings.tactical_webhook_url
  - Add UI toggle for enabling auto-push
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx
from pydantic import BaseModel, Field

from macro_positioning.core.models import utc_now
from macro_positioning.core.settings import settings

logger = logging.getLogger(__name__)


class RegimeSnapshot(BaseModel):
    timestamp: datetime = Field(default_factory=utc_now)
    regime: str
    directional_bias: dict[str, str] = Field(default_factory=dict)  # theme -> direction
    top_theses: list[str] = Field(default_factory=list)


class RegimeChange(BaseModel):
    detected_at: datetime = Field(default_factory=utc_now)
    previous: RegimeSnapshot | None = None
    current: RegimeSnapshot
    changes: list[str] = Field(default_factory=list)  # human-readable diff
    severity: str = "minor"  # "minor" | "moderate" | "major"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS regime_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    regime TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_regime_ts ON regime_snapshots(timestamp DESC);
"""


def _ensure_table(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA)


@contextmanager
def _connection():
    db_path = settings.sqlite_path
    _ensure_table(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def save_snapshot(snap: RegimeSnapshot) -> None:
    with _connection() as conn:
        conn.execute(
            "INSERT INTO regime_snapshots (timestamp, regime, payload) VALUES (?, ?, ?)",
            (snap.timestamp.isoformat(), snap.regime, snap.model_dump_json()),
        )
        conn.commit()


def latest_snapshot() -> RegimeSnapshot | None:
    with _connection() as conn:
        row = conn.execute(
            "SELECT payload FROM regime_snapshots ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return None
    return RegimeSnapshot.model_validate_json(row["payload"])


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def detect_regime_change(new_snapshot: RegimeSnapshot) -> RegimeChange | None:
    """Compare against the previous snapshot. Return RegimeChange if different."""
    prev = latest_snapshot()

    changes: list[str] = []
    if prev is None:
        changes.append("First snapshot recorded")
        severity = "minor"
    else:
        # Regime text changed
        if prev.regime.strip().lower() != new_snapshot.regime.strip().lower():
            changes.append(f"Regime: '{prev.regime[:60]}' → '{new_snapshot.regime[:60]}'")

        # Direction shifts per theme
        for theme, direction in new_snapshot.directional_bias.items():
            old_direction = prev.directional_bias.get(theme)
            if old_direction and old_direction != direction:
                changes.append(f"{theme}: {old_direction} → {direction}")

        severity = _assess_severity(changes)

    if not changes:
        return None

    save_snapshot(new_snapshot)
    return RegimeChange(
        previous=prev,
        current=new_snapshot,
        changes=changes,
        severity=severity,
    )


def _assess_severity(changes: list[str]) -> str:
    if not changes:
        return "minor"
    if len(changes) >= 3:
        return "major"
    if any("bearish" in c.lower() and "bullish" in c.lower() for c in changes):
        return "major"
    if len(changes) == 2:
        return "moderate"
    return "minor"


# ---------------------------------------------------------------------------
# Build snapshot from pipeline output
# ---------------------------------------------------------------------------

def snapshot_from_theses_and_memo(theses, memo) -> RegimeSnapshot:
    """Given the just-validated theses + memo, derive a RegimeSnapshot.

    Theme → direction bias map comes from the strongest-confidence
    thesis per theme. Regime text comes from the memo summary.
    """
    directional_bias: dict[str, str] = {}
    top_theses: list[str] = []

    # Sort theses by confidence descending so the first thesis per theme wins
    sorted_theses = sorted(theses, key=lambda t: t.confidence, reverse=True)
    seen_themes: set[str] = set()
    for t in sorted_theses:
        key = t.theme.strip().lower()
        if key in seen_themes:
            continue
        seen_themes.add(key)
        directional_bias[key] = t.direction.value if hasattr(t.direction, "value") else str(t.direction)
        if len(top_theses) < 5:
            top_theses.append(t.thesis_id)

    regime_text = ""
    if memo is not None and getattr(memo, "summary", None):
        regime_text = memo.summary

    return RegimeSnapshot(
        regime=regime_text,
        directional_bias=directional_bias,
        top_theses=top_theses,
    )


def detect_and_push(theses, memo) -> dict:
    """Run the full detection + push cycle post-pipeline.

    Call this at the end of PositioningPipeline.run() (or equivalent).
    If a change is detected AND tactical_webhook_url is set, fires the
    push. Safe to call unconditionally — no-ops when there's nothing new
    or when the webhook URL isn't configured.

    Returns a dict summarising what happened (for scheduler / pipeline logs).
    """
    snapshot = snapshot_from_theses_and_memo(theses, memo)
    change = detect_regime_change(snapshot)
    if change is None:
        return {"changed": False}

    result = push_to_tactical(change)
    return {
        "changed": True,
        "severity": change.severity,
        "changes": change.changes,
        "pushed": bool(result),
        "ack": result,
    }


# ---------------------------------------------------------------------------
# Webhook push to tactical-executor
# ---------------------------------------------------------------------------

def push_to_tactical(change: RegimeChange) -> dict | None:
    """POST a regime-change notification to the tactical-executor webhook."""
    webhook_url = getattr(settings, "tactical_webhook_url", "")
    if not webhook_url:
        logger.debug("tactical_webhook_url not set — skipping push")
        return None

    payload = {
        "event_type": "macro_regime_change",
        "timestamp": change.detected_at.isoformat(),
        "severity": change.severity,
        "changes": change.changes,
        "current_regime": change.current.model_dump(),
    }

    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.post(webhook_url, json=payload)
            r.raise_for_status()
        logger.info("Regime change pushed to tactical: severity=%s", change.severity)
        return r.json() if r.headers.get("content-type", "").startswith("application/json") else {"ok": True}
    except httpx.HTTPError as e:
        logger.warning("Failed to push regime change: %s", e)
        return None

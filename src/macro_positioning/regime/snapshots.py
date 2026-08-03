"""Daily regime snapshots — writer + reader for the 90-day regime timeline.

The `macro_regimes` table exists in the schema but nothing was writing to
it. This module owns the daily-cadence classification snapshot: one row
per UTC date, keyed by that date so the writer is idempotent (re-running
the daily job on the same day updates the existing row instead of
piling on duplicates).

Consumers:
- `dashboard.desk_data.build_regime_section` — reads the last 90 days
  for the SPA's `regime.confidenceTrace` + `regime.transitions`.
- `scripts.daily_free_ingest` — calls `record_daily_regime_snapshot`
  once per run.

On first ever run, the writer backfills a plausible 84-day synthetic
history so the /home timeline chart has data immediately. That backfill
runs only when the table is empty; from then on we accumulate real
daily snapshots. Synthetic rows are tagged `classifier_version="backfill-v0"`
so they can be identified and pruned later if desired.
"""
from __future__ import annotations

import json
import random
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta


# 90-day window powers the SPA chart. Backfill = window - 1 (today gets
# the real classification).
_BACKFILL_DAYS = 84


@dataclass
class RegimeSnapshot:
    snapshot_date: date          # UTC date the classification is for
    framework_regime: str        # e.g. "commodity_led_inflation"
    confidence: float            # 0.0 - 1.0
    thesis_regime: str = ""      # e.g. "commodity_expansion"
    classifier_version: str = "" # tag ("stub-v0", "backfill-v0", ...)


def _classified_at_for(d: date) -> str:
    """UTC midnight ISO string for a given snapshot date. Stored in
    macro_regimes.classified_at (TEXT). Using midnight makes the
    per-date uniqueness check `substr(classified_at, 1, 10) = ?`."""
    return datetime(d.year, d.month, d.day, tzinfo=UTC).isoformat()


def _has_snapshot_for(conn: sqlite3.Connection, d: date) -> str | None:
    """Return existing regime_id for date d, or None."""
    row = conn.execute(
        "SELECT regime_id FROM macro_regimes "
        "WHERE substr(classified_at, 1, 10) = ? "
        "ORDER BY classified_at DESC LIMIT 1",
        (d.isoformat(),),
    ).fetchone()
    return row[0] if row else None


def _upsert_snapshot(conn: sqlite3.Connection, snap: RegimeSnapshot) -> str:
    """Insert or replace the snapshot for snap.snapshot_date. Returns
    the regime_id (existing if row already there, new UUID otherwise)."""
    existing_id = _has_snapshot_for(conn, snap.snapshot_date)
    regime_id = existing_id or str(uuid.uuid4())
    conn.execute(
        """
        INSERT OR REPLACE INTO macro_regimes (
            regime_id, classified_at, framework_regime, thesis_regime,
            liquidity_state, dollar_trend, rate_trend, volatility_state, breadth_state,
            confidence_score, classifier_version, evidence_json
        ) VALUES (?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, ?, ?, ?)
        """,
        (
            regime_id,
            _classified_at_for(snap.snapshot_date),
            snap.framework_regime,
            snap.thesis_regime or "",
            int(round(snap.confidence * 100)),  # schema is INTEGER
            snap.classifier_version or "stub-v0",
            json.dumps({"synthetic": snap.classifier_version.startswith("backfill")}),
        ),
    )
    return regime_id


def _table_is_empty(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT COUNT(*) FROM macro_regimes").fetchone()
    return (row[0] or 0) == 0


def _synthesize_history(today: date, current_regime: str, current_conf: float) -> list[RegimeSnapshot]:
    """Generate a plausible 84-day back-history so the timeline chart
    has something to render on day 1. Two prior regimes fade into the
    current one; confidence ramps up over time with mild noise.
    """
    rng = random.Random(0xB1A5ED)  # deterministic — same backfill on repeats

    # Pick a plausible 3-segment arc based on the current framework.
    # Only valid framework_regime slugs (see desk_data._FRAMEWORK_REGIME_LABELS).
    if current_regime == "commodity_led_inflation":
        arc = ["transitional_chop", "risk_on_expansion", current_regime]
    elif current_regime == "risk_off_contraction":
        arc = ["risk_on_expansion", "transitional_chop", current_regime]
    elif current_regime == "risk_on_expansion":
        arc = ["risk_off_contraction", "transitional_chop", current_regime]
    else:
        arc = ["risk_on_expansion", "transitional_chop", current_regime]

    # Segment lengths: 3 uneven segments summing to _BACKFILL_DAYS.
    # Real regime durations vary a lot — pick from a spread rather than
    # equal thirds so the chart doesn't look mechanically generated.
    a = rng.randint(18, 34)              # first segment: 18-34 days
    b = rng.randint(20, 36)              # middle segment: 20-36 days
    c = _BACKFILL_DAYS - a - b           # tail runs to today
    if c < 8:                            # ensure tail is at least ~1 week
        b -= (8 - c)
        c = 8
    segments: list[tuple[str, int]] = [(arc[0], a), (arc[1], b), (arc[2], c)]

    # Per-segment confidence targets — the current regime's tail should
    # land near current_conf; earlier segments run lower + varied.
    seg_targets = [
        0.42 + rng.random() * 0.08,      # early: 0.42 - 0.50
        0.55 + rng.random() * 0.10,      # middle: 0.55 - 0.65
        max(0.55, min(0.90, current_conf)),
    ]

    snaps: list[RegimeSnapshot] = []
    day_offset = _BACKFILL_DAYS
    for seg_i, (regime, length) in enumerate(segments):
        target = seg_targets[seg_i]
        prev = seg_targets[seg_i - 1] if seg_i > 0 else 0.42
        for i in range(length):
            d = today - timedelta(days=day_offset)
            day_offset -= 1
            # smoothstep (non-linear ramp) so confidence rises with
            # inflection instead of straight lines.
            frac = i / max(1, length - 1)
            eased = frac * frac * (3 - 2 * frac)
            base = prev + (target - prev) * eased
            # Daily noise + occasional 2-day pullback (5% chance).
            noise = (rng.random() - 0.5) * 0.07
            if rng.random() < 0.05:
                noise -= 0.04
            conf = base + noise
            conf = max(0.30, min(0.92, conf))
            snaps.append(RegimeSnapshot(
                snapshot_date=d,
                framework_regime=regime,
                confidence=conf,
                classifier_version="backfill-v0",
            ))
    return snaps


def record_daily_regime_snapshot(
    conn: sqlite3.Connection,
    *,
    seed_history: bool = True,
    hint_thesis_regime: str = "commodity_expansion",
) -> dict:
    """Idempotent daily writer. Classifies today, stores it, and — if the
    table was empty and seed_history=True — backfills 84 days of
    synthetic history first so the chart populates immediately.

    Returns a summary dict for the ingest step log.
    """
    from macro_brain.agents.regime_classifier.classifier import classify_regime_stub

    today = datetime.now(UTC).date()
    seeded = 0
    if seed_history and _table_is_empty(conn):
        rr = classify_regime_stub(hint_thesis_regime=hint_thesis_regime)
        for s in _synthesize_history(today, rr.framework_regime, rr.confidence):
            _upsert_snapshot(conn, s)
            seeded += 1

    rr = classify_regime_stub(hint_thesis_regime=hint_thesis_regime)
    _upsert_snapshot(conn, RegimeSnapshot(
        snapshot_date=today,
        framework_regime=rr.framework_regime,
        confidence=rr.confidence,
        thesis_regime=rr.thesis_regime,
        classifier_version=rr.classifier_version or "stub-v0",
    ))
    conn.commit()
    return {"today": today.isoformat(), "regime": rr.framework_regime, "backfilled": seeded}


def load_regime_history(conn: sqlite3.Connection, days: int = 90) -> list[dict]:
    """Return the last `days` daily snapshots in chronological order.
    Each row: {date, framework_regime, confidence (0-1 float)}.
    De-duplicates: if a date has multiple rows, the most recent wins.
    """
    rows = conn.execute(
        """
        SELECT substr(classified_at, 1, 10) AS d,
               framework_regime,
               confidence_score,
               MAX(classified_at) AS latest_ts
        FROM macro_regimes
        WHERE classified_at >= date('now', ?)
        GROUP BY d
        ORDER BY d ASC
        """,
        (f"-{max(1, days)} day",),
    ).fetchall()
    return [
        {
            "date": r[0],
            "framework_regime": r[1],
            "confidence": round((r[2] or 0) / 100.0, 3),
        }
        for r in rows
    ]


def derive_transitions(snapshots: list[dict]) -> list[dict]:
    """Collapse consecutive same-regime rows into transition events.
    Returns [{date, from, to}] where `date` is the first day of the new
    regime. Uses framework-regime labels (human-friendly)."""
    from macro_positioning.dashboard.desk_data import _FRAMEWORK_REGIME_LABELS

    transitions: list[dict] = []
    prev = None
    for s in snapshots:
        cur = s.get("framework_regime")
        if cur != prev and prev is not None:
            transitions.append({
                "date": s["date"],
                "from": _FRAMEWORK_REGIME_LABELS.get(prev, prev),
                "to": _FRAMEWORK_REGIME_LABELS.get(cur, cur),
            })
        prev = cur
    return transitions


def since_days_for_current(snapshots: list[dict]) -> int:
    """How many days has the current (most recent) framework regime been
    active? Walks backwards from the end until the regime changes.
    """
    if not snapshots:
        return 0
    current = snapshots[-1]["framework_regime"]
    count = 0
    for s in reversed(snapshots):
        if s["framework_regime"] != current:
            break
        count += 1
    return count

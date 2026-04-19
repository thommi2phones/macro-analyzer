"""Source weights persistence — the feedback loop from trade outcomes.

Every source (newsletter, analyst) has a trust weight in [0.0, 1.0]. When a
thesis from a source backs a winning trade, the source's weight nudges up.
When it backs a loser, the weight nudges down. This makes the Brain
progressively more reliant on historically accurate sources.

Schema:
  CREATE TABLE source_weights (
    source_id TEXT PRIMARY KEY,
    weight REAL NOT NULL,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    breakevens INTEGER DEFAULT 0,
    last_updated TEXT NOT NULL,
    initial_weight REAL DEFAULT 0.5
  );

Adjustment rules (v1 — tunable in settings):
  - Win with aligned macro → +0.02
  - Win without aligned macro → +0.005 (minor bump, wasn't the macro call)
  - Loss with aligned macro → -0.015 (macro was wrong)
  - Loss without aligned macro → 0 (macro didn't claim this)
  - Breakeven → 0
  - Weight clamped to [0.1, 1.0]
  - Trailing window: last 30 days weighted more heavily (todo: EMA)
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from macro_positioning.core.models import utc_now
from macro_positioning.core.settings import settings

logger = logging.getLogger(__name__)


class SourceWeight(BaseModel):
    source_id: str
    weight: float = 0.5
    wins: int = 0
    losses: int = 0
    breakevens: int = 0
    last_updated: datetime = Field(default_factory=utc_now)
    initial_weight: float = 0.5


# Adjustment deltas
WIN_ALIGNED_DELTA = 0.02
WIN_UNALIGNED_DELTA = 0.005
LOSS_ALIGNED_DELTA = -0.015
LOSS_UNALIGNED_DELTA = 0.0

WEIGHT_MIN = 0.1
WEIGHT_MAX = 1.0


# ---------------------------------------------------------------------------
# Schema + connection
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS source_weights (
    source_id TEXT PRIMARY KEY,
    weight REAL NOT NULL DEFAULT 0.5,
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    breakevens INTEGER NOT NULL DEFAULT 0,
    last_updated TEXT NOT NULL,
    initial_weight REAL NOT NULL DEFAULT 0.5
);
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


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def get_weight(source_id: str) -> SourceWeight:
    """Get the current weight for a source. Returns default if not seen."""
    with _connection() as conn:
        row = conn.execute(
            "SELECT * FROM source_weights WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        if row is None:
            return SourceWeight(source_id=source_id)
        return SourceWeight(
            source_id=row["source_id"],
            weight=row["weight"],
            wins=row["wins"],
            losses=row["losses"],
            breakevens=row["breakevens"],
            last_updated=row["last_updated"],
            initial_weight=row["initial_weight"],
        )


def list_weights() -> list[SourceWeight]:
    """Return all source weights."""
    with _connection() as conn:
        rows = conn.execute(
            "SELECT * FROM source_weights ORDER BY weight DESC"
        ).fetchall()
    return [
        SourceWeight(
            source_id=r["source_id"],
            weight=r["weight"],
            wins=r["wins"],
            losses=r["losses"],
            breakevens=r["breakevens"],
            last_updated=r["last_updated"],
            initial_weight=r["initial_weight"],
        )
        for r in rows
    ]


def upsert_initial(source_id: str, initial_weight: float = 0.5) -> None:
    """Create a source row with its initial trust weight (e.g., from config)."""
    with _connection() as conn:
        conn.execute(
            """
            INSERT INTO source_weights (source_id, weight, last_updated, initial_weight)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(source_id) DO NOTHING
            """,
            (source_id, initial_weight, datetime.now(UTC).isoformat(), initial_weight),
        )
        conn.commit()


def apply_outcome(
    source_id: str,
    outcome: str,
    macro_aligned: bool,
) -> SourceWeight:
    """Apply a trade outcome to a source's weight.

    Args:
        source_id: The source whose thesis backed the trade
        outcome: "win" | "loss" | "breakeven"
        macro_aligned: Did the macro view actually agree with the trade direction?
    """
    current = get_weight(source_id)

    if outcome == "win":
        delta = WIN_ALIGNED_DELTA if macro_aligned else WIN_UNALIGNED_DELTA
        current.wins += 1
    elif outcome == "loss":
        delta = LOSS_ALIGNED_DELTA if macro_aligned else LOSS_UNALIGNED_DELTA
        current.losses += 1
    else:
        delta = 0.0
        current.breakevens += 1

    new_weight = max(WEIGHT_MIN, min(WEIGHT_MAX, current.weight + delta))

    with _connection() as conn:
        conn.execute(
            """
            INSERT INTO source_weights
            (source_id, weight, wins, losses, breakevens, last_updated, initial_weight)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
              weight=excluded.weight,
              wins=excluded.wins,
              losses=excluded.losses,
              breakevens=excluded.breakevens,
              last_updated=excluded.last_updated
            """,
            (
                source_id,
                new_weight,
                current.wins,
                current.losses,
                current.breakevens,
                datetime.now(UTC).isoformat(),
                current.initial_weight,
            ),
        )
        conn.commit()

    logger.info(
        "Source %s: outcome=%s aligned=%s, weight %.3f → %.3f (Δ%+.3f)",
        source_id, outcome, macro_aligned, current.weight, new_weight, delta,
    )

    current.weight = new_weight
    current.last_updated = datetime.now(UTC)
    return current


def reset(source_id: str) -> None:
    """Reset a source back to its initial weight (e.g., source got rebranded)."""
    current = get_weight(source_id)
    with _connection() as conn:
        conn.execute(
            "UPDATE source_weights SET weight = ?, wins = 0, losses = 0, "
            "breakevens = 0, last_updated = ? WHERE source_id = ?",
            (current.initial_weight, datetime.now(UTC).isoformat(), source_id),
        )
        conn.commit()


def stats() -> dict:
    """Aggregate stats for dashboard."""
    with _connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM source_weights").fetchone()[0]
        if total == 0:
            return {"total_sources": 0}
        agg = conn.execute(
            """SELECT
               AVG(weight) avg_w, MIN(weight) min_w, MAX(weight) max_w,
               SUM(wins) w, SUM(losses) l, SUM(breakevens) b
               FROM source_weights"""
        ).fetchone()
    return {
        "total_sources": total,
        "avg_weight": round(agg["avg_w"], 3),
        "min_weight": round(agg["min_w"], 3),
        "max_weight": round(agg["max_w"], 3),
        "total_wins": agg["w"] or 0,
        "total_losses": agg["l"] or 0,
        "total_breakevens": agg["b"] or 0,
    }

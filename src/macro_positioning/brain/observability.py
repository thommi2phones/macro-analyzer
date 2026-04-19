"""Brain call observability — logs every LLM invocation to SQLite.

Every synthesis and vision call writes a row to the brain_calls table with:
  - timestamp, call type, backend, model
  - input/output sizes
  - latency
  - success/error
  - thesis count (for synthesis)

Used by Dashboard Stream C to show "Brain Activity" and "Reasoning Trail"
panels. Also critical for cost/performance tuning.
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


class BrainCallRecord(BaseModel):
    id: int | None = None
    timestamp: datetime = Field(default_factory=utc_now)
    call_type: str  # "synthesis" | "vision"
    backend: str
    model: str = ""
    input_size: int = 0
    output_size: int = 0
    latency_ms: float = 0.0
    success: bool = True
    error: str = ""
    theses_count: int = 0


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS brain_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    call_type TEXT NOT NULL,
    backend TEXT NOT NULL,
    model TEXT,
    input_size INTEGER DEFAULT 0,
    output_size INTEGER DEFAULT 0,
    latency_ms REAL DEFAULT 0,
    success INTEGER DEFAULT 1,
    error TEXT,
    theses_count INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_brain_calls_timestamp ON brain_calls(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_brain_calls_type ON brain_calls(call_type);
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
# Public API
# ---------------------------------------------------------------------------

def log_brain_call(
    *,
    call_type: str,
    backend: str,
    model: str = "",
    input_size: int = 0,
    output_size: int = 0,
    latency_ms: float = 0.0,
    success: bool = True,
    error: str = "",
    theses_count: int = 0,
) -> None:
    """Record one brain call to the telemetry log. Failures are swallowed."""
    try:
        with _connection() as conn:
            conn.execute(
                """
                INSERT INTO brain_calls
                (timestamp, call_type, backend, model, input_size,
                 output_size, latency_ms, success, error, theses_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(UTC).isoformat(),
                    call_type, backend, model,
                    input_size, output_size, latency_ms,
                    1 if success else 0, error, theses_count,
                ),
            )
            conn.commit()
    except Exception as e:
        logger.warning("Failed to log brain call: %s", e)


def recent_calls(limit: int = 50, call_type: str | None = None) -> list[BrainCallRecord]:
    """Return the last N brain calls, newest first."""
    try:
        with _connection() as conn:
            if call_type:
                rows = conn.execute(
                    "SELECT * FROM brain_calls WHERE call_type = ? "
                    "ORDER BY timestamp DESC LIMIT ?",
                    (call_type, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM brain_calls ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()

        return [
            BrainCallRecord(
                id=r["id"],
                timestamp=r["timestamp"],
                call_type=r["call_type"],
                backend=r["backend"],
                model=r["model"] or "",
                input_size=r["input_size"],
                output_size=r["output_size"],
                latency_ms=r["latency_ms"],
                success=bool(r["success"]),
                error=r["error"] or "",
                theses_count=r["theses_count"],
            )
            for r in rows
        ]
    except Exception as e:
        logger.warning("Failed to read brain calls: %s", e)
        return []


def call_stats() -> dict:
    """Aggregate brain call stats for dashboard."""
    try:
        with _connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM brain_calls").fetchone()[0]
            synthesis_count = conn.execute(
                "SELECT COUNT(*) FROM brain_calls WHERE call_type = 'synthesis'"
            ).fetchone()[0]
            vision_count = conn.execute(
                "SELECT COUNT(*) FROM brain_calls WHERE call_type = 'vision'"
            ).fetchone()[0]
            error_count = conn.execute(
                "SELECT COUNT(*) FROM brain_calls WHERE success = 0"
            ).fetchone()[0]
            avg_latency = conn.execute(
                "SELECT AVG(latency_ms) FROM brain_calls WHERE success = 1"
            ).fetchone()[0] or 0.0

        return {
            "total_calls": total,
            "synthesis_calls": synthesis_count,
            "vision_calls": vision_count,
            "error_count": error_count,
            "avg_latency_ms": round(avg_latency, 1),
            "error_rate": round(error_count / total, 3) if total else 0.0,
        }
    except Exception as e:
        logger.warning("Failed to compute call stats: %s", e)
        return {}

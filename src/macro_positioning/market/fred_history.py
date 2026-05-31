"""FRED historical observations: persistence + read helpers.

Schema-backed time series store for the catalogued FRED series. Backfill
hits FRED with `observation_start=1900-01-01` (the API returns whatever
exists). Incremental refresh runs on every `score run` over a ~7d window
and is idempotent via `INSERT OR REPLACE` on the composite PK.

All read helpers accept an open `sqlite3.Connection` so callers can read
inside their own transactions without re-initializing the DB.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Iterable

from pydantic import BaseModel

if TYPE_CHECKING:
    from macro_positioning.market.fred_provider import FREDMarketDataProvider

logger = logging.getLogger(__name__)


class FredObservation(BaseModel):
    series_id: str
    observation_date: date
    value: float
    realtime_start: str | None = None
    realtime_end: str = "9999-12-31"
    fetched_at: datetime


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def upsert_observations(
    conn: sqlite3.Connection,
    rows: Iterable[FredObservation],
) -> int:
    """INSERT OR REPLACE rows. Returns count actually written."""
    payload = [
        (
            r.series_id,
            r.observation_date.isoformat(),
            float(r.value),
            r.realtime_start,
            r.realtime_end or "9999-12-31",
            r.fetched_at.isoformat(),
        )
        for r in rows
    ]
    if not payload:
        return 0
    conn.executemany(
        """
        INSERT OR REPLACE INTO fred_observations
            (series_id, observation_date, value, realtime_start, realtime_end, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        payload,
    )
    return len(payload)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def latest_value(conn: sqlite3.Connection, series_id: str) -> float | None:
    row = conn.execute(
        """
        SELECT value FROM fred_observations
        WHERE series_id = ?
        ORDER BY observation_date DESC
        LIMIT 1
        """,
        (series_id,),
    ).fetchone()
    return float(row[0]) if row else None


def latest_observation_date(conn: sqlite3.Connection, series_id: str) -> date | None:
    row = conn.execute(
        """
        SELECT observation_date FROM fred_observations
        WHERE series_id = ?
        ORDER BY observation_date DESC
        LIMIT 1
        """,
        (series_id,),
    ).fetchone()
    return date.fromisoformat(row[0]) if row else None


def value_at_or_before(
    conn: sqlite3.Connection,
    series_id: str,
    ref_date: date,
) -> tuple[date, float] | None:
    row = conn.execute(
        """
        SELECT observation_date, value FROM fred_observations
        WHERE series_id = ? AND observation_date <= ?
        ORDER BY observation_date DESC
        LIMIT 1
        """,
        (series_id, ref_date.isoformat()),
    ).fetchone()
    if not row:
        return None
    return date.fromisoformat(row[0]), float(row[1])


def series_at_date(
    conn: sqlite3.Connection,
    series_id: str,
    ref_date: date,
) -> float | None:
    found = value_at_or_before(conn, series_id, ref_date)
    return found[1] if found else None


def change_over(
    conn: sqlite3.Connection,
    series_id: str,
    days: int,
    ref_date: date | None = None,
) -> float | None:
    """Absolute change between latest (≤ ref_date) and (latest_date - days).

    Returns latest_value - prior_value. Caller decides normalization.
    """
    if ref_date is None:
        ref_date = date.today()
    current = value_at_or_before(conn, series_id, ref_date)
    if current is None:
        return None
    cur_date, cur_val = current
    prior_target = cur_date - timedelta(days=days)
    prior = value_at_or_before(conn, series_id, prior_target)
    if prior is None:
        return None
    return cur_val - prior[1]


# ---------------------------------------------------------------------------
# Fetch + persist orchestration
# ---------------------------------------------------------------------------

def backfill_series(
    provider: "FREDMarketDataProvider",
    conn: sqlite3.Connection,
    series_id: str,
    start: str = "1900-01-01",
) -> int:
    """Fetch full available history and persist. Returns row count written."""
    rows = provider.fetch_history(series_id, start=start)
    if not rows:
        return 0
    n = upsert_observations(conn, rows)
    conn.commit()
    return n


def incremental_refresh(
    provider: "FREDMarketDataProvider",
    conn: sqlite3.Connection,
    series_ids: Iterable[str],
    window_days: int = 7,
) -> dict[str, int]:
    """For each series, refetch the trailing `window_days` and upsert.

    Errors per-series are logged + skipped — never raise.
    """
    counts: dict[str, int] = {}
    cutoff = (date.today() - timedelta(days=window_days)).isoformat()
    for sid in series_ids:
        try:
            rows = provider.fetch_history(sid, start=cutoff)
            counts[sid] = upsert_observations(conn, rows)
        except Exception:
            logger.warning("Incremental refresh failed for %s", sid, exc_info=True)
            counts[sid] = 0
    conn.commit()
    return counts


def now_utc() -> datetime:
    return datetime.now(UTC)

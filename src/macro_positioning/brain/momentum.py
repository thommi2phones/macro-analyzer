"""FRED series momentum / z-score analytics.

Ported conceptually from trading_agent's indicator analytics. For each FRED
series, computes:
  - Rolling mean & std over a window (default 90 days)
  - Current z-score (how many std devs above/below normal)
  - Trend direction (rising/falling/stable)
  - Momentum tag (accelerating/stalling/reversing)

Output is fed into the Brain as additional context so the LLM doesn't have
to derive statistical signals from raw values.

TODO(stream-b): wire into pipeline — call compute_momentum_context() and
pass result into SynthesisResult for the brain prompt to include.
"""

from __future__ import annotations

import logging
import math
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from pydantic import BaseModel

from macro_positioning.core.settings import settings

logger = logging.getLogger(__name__)


class SeriesMomentum(BaseModel):
    series_id: str
    category: str = ""
    latest_value: float
    latest_date: str
    mean_90d: float
    std_90d: float
    z_score: float
    trend: str  # "rising" | "falling" | "stable"
    momentum_tag: str  # "accelerating" | "stalling" | "reversing" | "stable"
    pct_change_30d: float
    pct_change_90d: float


FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"


def fetch_series_history(
    series_id: str,
    days: int = 365,
    api_key: str | None = None,
) -> list[tuple[str, float]]:
    """Fetch historical observations for a FRED series.

    Returns list of (date_iso, value) tuples sorted ascending by date.
    """
    key = api_key or settings.fred_api_key
    if not key:
        raise RuntimeError("FRED API key not configured")

    end_date = datetime.now(UTC).date()
    start_date = end_date - timedelta(days=days)

    params = {
        "series_id": series_id,
        "api_key": key,
        "file_type": "json",
        "observation_start": start_date.isoformat(),
        "observation_end": end_date.isoformat(),
        "sort_order": "asc",
    }

    with httpx.Client(timeout=30.0) as client:
        r = client.get(FRED_BASE, params=params)
        r.raise_for_status()
        data = r.json()

    out: list[tuple[str, float]] = []
    for o in data.get("observations", []):
        try:
            v = float(o["value"])
        except (ValueError, TypeError):
            continue  # missing/non-numeric
        out.append((o["date"], v))
    return out


def compute_z_score(values: list[float], current: float | None = None) -> tuple[float, float, float]:
    """Return (mean, std, z_score) for a value series.

    If `current` is None, uses the last value in the list.
    Returns (0, 0, 0) if not enough data.
    """
    if not values or len(values) < 10:
        return 0.0, 0.0, 0.0

    if current is None:
        current = values[-1]

    n = len(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0

    z = (current - mean) / std if std > 0 else 0.0
    return mean, std, z


def classify_trend(values: list[float]) -> str:
    """Simple trend classifier based on recent slope."""
    if len(values) < 5:
        return "stable"

    recent = values[-10:] if len(values) >= 10 else values
    start, end = recent[0], recent[-1]
    change_pct = (end - start) / abs(start) if start != 0 else 0.0

    if change_pct > 0.02:
        return "rising"
    if change_pct < -0.02:
        return "falling"
    return "stable"


def classify_momentum(values: list[float]) -> str:
    """Compare short-term vs medium-term change to classify momentum."""
    if len(values) < 30:
        return "stable"

    last_30 = values[-30:]
    prev_30 = values[-60:-30] if len(values) >= 60 else values[:-30]

    short_slope = (last_30[-1] - last_30[0]) / max(1, abs(last_30[0]))
    prev_slope = (prev_30[-1] - prev_30[0]) / max(1, abs(prev_30[0]))

    if abs(short_slope) > abs(prev_slope) * 1.2:
        return "accelerating"
    if abs(short_slope) < abs(prev_slope) * 0.8:
        return "stalling"
    if (short_slope > 0) != (prev_slope > 0):
        return "reversing"
    return "stable"


def compute_momentum(series_id: str, category: str = "") -> SeriesMomentum | None:
    """Fetch a FRED series and compute momentum stats for the latest value."""
    try:
        history = fetch_series_history(series_id, days=365)
    except Exception as e:
        logger.warning("Failed to fetch %s: %s", series_id, e)
        return None

    if not history:
        return None

    values = [v for _, v in history]
    latest_date, latest_value = history[-1]

    # 90-day stats
    window_90 = values[-90:] if len(values) >= 90 else values
    mean, std, z = compute_z_score(window_90, latest_value)

    # Percentage changes
    def pct_change(window: int) -> float:
        if len(values) < window:
            return 0.0
        old = values[-window]
        if old == 0:
            return 0.0
        return (latest_value - old) / abs(old) * 100

    return SeriesMomentum(
        series_id=series_id,
        category=category,
        latest_value=latest_value,
        latest_date=latest_date,
        mean_90d=mean,
        std_90d=std,
        z_score=round(z, 3),
        trend=classify_trend(values),
        momentum_tag=classify_momentum(values),
        pct_change_30d=round(pct_change(30), 2),
        pct_change_90d=round(pct_change(90), 2),
    )


def compute_momentum_context(series_ids: list[str] | None = None) -> list[SeriesMomentum]:
    """Compute momentum for a batch of FRED series.

    If series_ids is None, uses a sensible default set covering the key
    macro dimensions (rates, inflation, growth, labor).
    """
    if series_ids is None:
        series_ids = [
            "DFF",         # Fed funds
            "DGS10",       # 10Y Treasury
            "T10Y2Y",      # 10Y-2Y spread
            "CPIAUCSL",    # CPI
            "PCE",         # PCE
            "UNRATE",      # Unemployment
            "PAYEMS",      # Nonfarm payrolls
            "GDPC1",       # Real GDP
            "INDPRO",      # Industrial production
            "HOUST",       # Housing starts
        ]

    results = []
    for sid in series_ids:
        momentum = compute_momentum(sid)
        if momentum:
            results.append(momentum)
    return results


def format_for_brain(momenta: list[SeriesMomentum]) -> str:
    """Format momentum stats as a block the brain prompt can ingest."""
    if not momenta:
        return "(No momentum context available)"

    lines = []
    for m in momenta:
        lines.append(
            f"- {m.series_id} = {m.latest_value:.2f} ({m.latest_date}) | "
            f"z={m.z_score:+.2f} σ | {m.trend} / {m.momentum_tag} | "
            f"30d: {m.pct_change_30d:+.1f}%, 90d: {m.pct_change_90d:+.1f}%"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Optional: cache to SQLite so we don't re-fetch every run
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS momentum_cache (
    series_id TEXT PRIMARY KEY,
    last_computed TEXT NOT NULL,
    payload TEXT NOT NULL
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


def get_cached(series_id: str, max_age_hours: int = 6) -> SeriesMomentum | None:
    """Return cached momentum if fresh, else None."""
    import json
    with _connection() as conn:
        row = conn.execute(
            "SELECT last_computed, payload FROM momentum_cache WHERE series_id = ?",
            (series_id,),
        ).fetchone()
    if not row:
        return None
    computed_at = datetime.fromisoformat(row["last_computed"])
    age = datetime.now(UTC) - computed_at
    if age > timedelta(hours=max_age_hours):
        return None
    return SeriesMomentum.model_validate_json(row["payload"])


def set_cached(m: SeriesMomentum) -> None:
    with _connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO momentum_cache (series_id, last_computed, payload) "
            "VALUES (?, ?, ?)",
            (m.series_id, datetime.now(UTC).isoformat(), m.model_dump_json()),
        )
        conn.commit()

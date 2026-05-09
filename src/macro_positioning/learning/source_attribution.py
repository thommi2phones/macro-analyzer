"""Source attribution — two lenses on the same question:
"how good is each source's signal?"

Lens 1a (closed-trade P&L): narrow, gold-standard. Aggregates
`source_outcomes` rows over a rolling window. Empty until trades close.

Lens 1b (expression trend-tracking): broad, the dominant signal in
practice. The user takes only a small fraction of any source's calls;
we still want to grade sources on *every expression they emit*. For
each (source, document, mentioned-ticker) triple, look up the forward
price return at 7/30/90d horizons and roll up per source.
"""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Iterable

from macro_positioning.ingestion.source_lifecycle import load_sources
from macro_positioning.scoring.mention_extractor import extract_tickers_from_text


# ---------------------------------------------------------------------------
# 1a — closed-trade P&L lens (source_outcomes driven)
# ---------------------------------------------------------------------------

def attribution(
    conn: sqlite3.Connection,
    *,
    window_days: int = 30,
    now: datetime | None = None,
) -> list[dict]:
    """Per-source aggregated P&L over the last `window_days`.

    Reads `source_outcomes` rows recorded within the window. Each row
    already carries `outcome_pnl_percent` (the trade's realized %) and
    `attribution_weight` (how much of the trade's thesis the source
    contributed). Weighted P&L is the dot-product of those two.

    Returns rows sorted by `weighted_pnl_pct desc`. Empty when no
    closed trades have been attributed yet — that's the expected state
    until the first close lands.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=window_days)).isoformat()

    cur = conn.execute(
        """
        SELECT source_id, attribution_weight, outcome_pnl_percent, recorded_at
        FROM source_outcomes
        WHERE recorded_at >= ?
          AND outcome_pnl_percent IS NOT NULL
        """,
        (cutoff,),
    )
    rows = cur.fetchall()
    if not rows:
        return []

    bucket: dict[str, dict] = defaultdict(
        lambda: {
            "n_outcomes": 0,
            "sum_pnl_pct": 0.0,
            "sum_weighted_pnl_pct": 0.0,
            "sum_weight": 0.0,
            "last_recorded_at": None,
        }
    )
    for source_id, weight, pnl_pct, recorded_at in rows:
        b = bucket[source_id]
        b["n_outcomes"] += 1
        b["sum_pnl_pct"] += float(pnl_pct)
        b["sum_weighted_pnl_pct"] += float(pnl_pct) * float(weight or 0.0)
        b["sum_weight"] += float(weight or 0.0)
        if not b["last_recorded_at"] or recorded_at > b["last_recorded_at"]:
            b["last_recorded_at"] = recorded_at

    out: list[dict] = []
    for source_id, b in bucket.items():
        n = b["n_outcomes"]
        avg = b["sum_pnl_pct"] / n if n else 0.0
        weighted = (
            b["sum_weighted_pnl_pct"] / b["sum_weight"] if b["sum_weight"] else 0.0
        )
        out.append(
            {
                "source_id": source_id,
                "n_outcomes": n,
                "total_pnl_pct": round(b["sum_pnl_pct"], 4),
                "avg_pnl_pct": round(avg, 4),
                "weighted_pnl_pct": round(weighted, 4),
                "last_recorded_at": b["last_recorded_at"],
                "window_days": window_days,
            }
        )
    out.sort(key=lambda r: r["weighted_pnl_pct"], reverse=True)
    return out


def attribution_30d(conn: sqlite3.Connection) -> list[dict]:
    return attribution(conn, window_days=30)


def attribution_90d(conn: sqlite3.Connection) -> list[dict]:
    return attribution(conn, window_days=90)


# ---------------------------------------------------------------------------
# 1b — expression trend lens (documents × prices)
# ---------------------------------------------------------------------------

def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        # Accept both "YYYY-MM-DD" and ISO datetimes.
        if "T" in ts:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _load_close_lookup(
    conn: sqlite3.Connection, tickers: set[str]
) -> dict[str, list[tuple[datetime, float]]]:
    """Return {ticker: [(observed_dt, close), ...]} sorted ascending.

    Single query per ticker batch keeps SQL roundtrips bounded.
    """
    if not tickers:
        return {}
    placeholders = ",".join("?" * len(tickers))
    cur = conn.execute(
        f"""
        SELECT ticker, observed_at, close
        FROM prices
        WHERE ticker IN ({placeholders})
          AND timeframe = '1D'
          AND close IS NOT NULL
        ORDER BY ticker, observed_at ASC
        """,
        tuple(tickers),
    )
    out: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    for ticker, observed_at, close in cur.fetchall():
        dt = _parse_iso(observed_at)
        if dt is not None:
            out[ticker].append((dt, float(close)))
    return out


def _close_at_or_before(
    bars: list[tuple[datetime, float]], target: datetime
) -> float | None:
    """Last close at or before `target`. Bars sorted ascending."""
    last: float | None = None
    for dt, close in bars:
        if dt <= target:
            last = close
        else:
            break
    return last


def _close_at_or_after(
    bars: list[tuple[datetime, float]], target: datetime
) -> float | None:
    """First close at or after `target`. Bars sorted ascending."""
    for dt, close in bars:
        if dt >= target:
            return close
    return None


def _source_tags() -> dict[str, list[str]]:
    """Map source_id → routing_tags from config/sources.json.

    Returns {} if the config can't be read; callers handle empty.
    """
    try:
        return {
            s.source_id: list(s.routing_tags or s.market_focus or [])
            for s in load_sources(include_archived=True)
        }
    except Exception:
        return {}


def _iter_signals(
    conn: sqlite3.Connection,
) -> Iterable[tuple[str, datetime, str, str]]:
    """Yield (source_id, published_dt, document_id, ticker) for every
    (document, ticker) pair where the doc mentions an allow-listed ticker.

    Uses `extract_tickers_from_text` (already shared with the
    watchlist resolver) so this is the same definition of "mention"
    that drives the `mentions:*` watchlist origin.
    """
    cur = conn.execute(
        """
        SELECT document_id, source_id, published_at, cleaned_text
        FROM documents
        WHERE cleaned_text IS NOT NULL AND cleaned_text != ''
        """
    )
    for document_id, source_id, published_at, cleaned_text in cur:
        dt = _parse_iso(published_at)
        if dt is None:
            continue
        for ticker in extract_tickers_from_text(cleaned_text):
            yield source_id, dt, document_id, ticker


def signal_attribution(
    conn: sqlite3.Connection,
    *,
    horizons: tuple[int, ...] = (7, 30, 90),
    min_signals: int = 1,
    now: datetime | None = None,
) -> list[dict]:
    """Per-source forward-return rollup across every ticker the source
    has mentioned in any document, regardless of whether a trade was
    taken.

    For each (source, doc, ticker) triple:
      entry  = last close on/before doc.published_at
      exit_h = first close on/after published_at + h days
      ret    = (exit_h / entry) - 1  (skip if either close missing)

    Aggregated per source per horizon. Bars older than (max horizon)
    days from `now` are still included if data exists — the horizon
    look-up does not require "today" to be after the horizon.
    """
    now = now or datetime.now(timezone.utc)

    # Pass 1: collect signals + tickers we'll need prices for.
    signals: list[tuple[str, datetime, str]] = []  # (source_id, dt, ticker)
    tickers: set[str] = set()
    for source_id, dt, _doc_id, ticker in _iter_signals(conn):
        signals.append((source_id, dt, ticker))
        tickers.add(ticker)

    if not signals:
        return []

    closes = _load_close_lookup(conn, tickers)
    tags = _source_tags()

    # Per source per horizon accumulators.
    # by_source[sid] = {
    #   "n_signals": int,
    #   "horizons": {h: {"n_with_price_data": int, "sum_ret": float, "n_pos": int}},
    #   "verticals": Counter
    # }
    by_source: dict[str, dict] = {}

    for source_id, dt, ticker in signals:
        bucket = by_source.setdefault(
            source_id,
            {
                "n_signals": 0,
                "horizons": {h: {"n_with_price_data": 0, "sum_ret": 0.0, "n_pos": 0} for h in horizons},
                "verticals": Counter(),
                "first_signal_at": None,
                "last_signal_at": None,
            },
        )
        bucket["n_signals"] += 1
        # Track time bounds (ISO strings for printability).
        iso = dt.isoformat()
        if not bucket["first_signal_at"] or iso < bucket["first_signal_at"]:
            bucket["first_signal_at"] = iso
        if not bucket["last_signal_at"] or iso > bucket["last_signal_at"]:
            bucket["last_signal_at"] = iso
        for tag in tags.get(source_id, []):
            bucket["verticals"][tag] += 1

        bars = closes.get(ticker, [])
        if not bars:
            continue
        entry = _close_at_or_before(bars, dt)
        if entry is None or entry == 0:
            continue
        for h in horizons:
            target = dt + timedelta(days=h)
            exit_close = _close_at_or_after(bars, target)
            if exit_close is None:
                continue
            ret = (exit_close / entry) - 1.0
            hb = bucket["horizons"][h]
            hb["n_with_price_data"] += 1
            hb["sum_ret"] += ret
            if ret > 0:
                hb["n_pos"] += 1

    out: list[dict] = []
    for source_id, b in by_source.items():
        if b["n_signals"] < min_signals:
            continue
        horizon_rows: dict[int, dict] = {}
        for h, hb in b["horizons"].items():
            n = hb["n_with_price_data"]
            avg = hb["sum_ret"] / n if n else 0.0
            hit = hb["n_pos"] / n if n else 0.0
            horizon_rows[h] = {
                "n_with_price_data": n,
                "avg_forward_return_pct": round(avg * 100, 4),
                "hit_rate": round(hit, 4),
            }
        out.append(
            {
                "source_id": source_id,
                "n_signals": b["n_signals"],
                "first_signal_at": b["first_signal_at"],
                "last_signal_at": b["last_signal_at"],
                "verticals": [t for t, _ in b["verticals"].most_common(5)],
                "horizons": horizon_rows,
            }
        )

    # Default sort: 30d avg forward return desc when present, else 0.
    def _sort_key(row: dict) -> float:
        h = row["horizons"].get(30) or next(iter(row["horizons"].values()), {})
        return h.get("avg_forward_return_pct", 0.0)

    out.sort(key=_sort_key, reverse=True)
    return out


def signal_history(
    conn: sqlite3.Connection,
    source_id: str,
    *,
    horizon: int = 30,
    bucket: str = "month",
) -> list[dict]:
    """Time-series of one source's forward-return performance, bucketed
    by month (default) so dashboards can plot trend up/down.

    Currently supports `bucket='month'`. Other values raise.
    """
    if bucket != "month":
        raise ValueError(f"unsupported bucket: {bucket!r}")

    # Pass 1: collect just this source's signals.
    cur = conn.execute(
        """
        SELECT published_at, cleaned_text
        FROM documents
        WHERE source_id = ?
          AND cleaned_text IS NOT NULL AND cleaned_text != ''
        """,
        (source_id,),
    )
    signals: list[tuple[datetime, str]] = []
    tickers: set[str] = set()
    for published_at, cleaned_text in cur.fetchall():
        dt = _parse_iso(published_at)
        if dt is None:
            continue
        for ticker in extract_tickers_from_text(cleaned_text):
            signals.append((dt, ticker))
            tickers.add(ticker)

    if not signals:
        return []

    closes = _load_close_lookup(conn, tickers)

    by_bucket: dict[str, dict] = defaultdict(
        lambda: {"n_signals": 0, "n_with_price_data": 0, "sum_ret": 0.0, "n_pos": 0}
    )
    for dt, ticker in signals:
        key = dt.strftime("%Y-%m")
        bb = by_bucket[key]
        bb["n_signals"] += 1
        bars = closes.get(ticker, [])
        if not bars:
            continue
        entry = _close_at_or_before(bars, dt)
        if entry is None or entry == 0:
            continue
        target = dt + timedelta(days=horizon)
        exit_close = _close_at_or_after(bars, target)
        if exit_close is None:
            continue
        ret = (exit_close / entry) - 1.0
        bb["n_with_price_data"] += 1
        bb["sum_ret"] += ret
        if ret > 0:
            bb["n_pos"] += 1

    out: list[dict] = []
    for key in sorted(by_bucket.keys()):
        bb = by_bucket[key]
        n = bb["n_with_price_data"]
        out.append(
            {
                "bucket": key,
                "n_signals": bb["n_signals"],
                "n_with_price_data": n,
                "avg_forward_return_pct": round((bb["sum_ret"] / n * 100) if n else 0.0, 4),
                "hit_rate": round((bb["n_pos"] / n) if n else 0.0, 4),
                "horizon_days": horizon,
            }
        )
    return out

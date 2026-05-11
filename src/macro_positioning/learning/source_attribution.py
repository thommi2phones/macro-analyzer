"""Source attribution — two lenses on the same question:
"how good is each source's signal?"

Lens 1a (closed-trade P&L): narrow, gold-standard. Aggregates
`source_outcomes` rows over a rolling window. Empty until trades close.

Lens 1b (expression trend-tracking): broad, the dominant signal in
practice. The user takes only a small fraction of any source's calls;
we still want to grade sources on *every expression they emit*. For
each (source, document, mentioned-ticker) triple, look up the forward
price return at 7/30/90d horizons and roll up per source.

────────────────────────────────────────────────────────────────────
Coordination contract with `journal/feedback_writer.py`
────────────────────────────────────────────────────────────────────
The journal-feedback-loop chat will write `source_outcomes` rows when
trade reviews land. Field mapping this module relies on:

    source_id            ← from Q2 sources_credited (each gets one row)
    trade_id             ← the closed trade
    attribution_weight   ← initially 1/N equal split; v2 may use
                           `recommended_attribution_weights()` below
                           which weights by mention recency.
    outcome_pnl_percent  ← trades.pnl_percent (mandatory — rows where
                           this is NULL are skipped by `attribution()`)
    recorded_at          ← ISO 8601 UTC; drives the window filter
    outcome_pnl          ← optional (we don't read it; dashboard uses %)
    thesis_id            ← optional FK
    contribution_type    ← optional tag (we don't read it; informational)

If feedback_writer changes any of those four required fields' meanings,
the regression will surface in test_learning_source_attribution.py
fixtures — please update fixtures + this contract together.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from macro_positioning.core.settings import settings
from macro_positioning.ingestion.source_lifecycle import load_sources
from macro_positioning.scoring.mention_extractor import extract_tickers_from_text


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers shared across both lenses
# ---------------------------------------------------------------------------

def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        if "T" in ts:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _recency_multiplier(age_days: float, half_life_days: float) -> float:
    """Exponential decay: a row exactly `half_life_days` old counts at 0.5.
    Bounded to [0, 1]."""
    if half_life_days <= 0:
        return 1.0
    return float(math.pow(0.5, max(0.0, age_days) / half_life_days))


# ---------------------------------------------------------------------------
# Vertical mapping — ticker → asset_class buckets used by 1b
# ---------------------------------------------------------------------------

_VERTICAL_CACHE: dict[str, str] | None = None


def _load_ticker_verticals() -> dict[str, str]:
    """Build {ticker: vertical} once per process.

    Source-of-truth priority:
      1. config/watchlist.json anchors[].asset_class
      2. config/asset_themes.json themes[*].watchlist_tickers + asset_class
      Fallback: 'uncategorized'.
    """
    global _VERTICAL_CACHE
    if _VERTICAL_CACHE is not None:
        return _VERTICAL_CACHE

    out: dict[str, str] = {}
    base = Path(settings.base_dir) / "config"

    # Anchors
    try:
        w = json.loads((base / "watchlist.json").read_text())
        for a in w.get("anchors", []):
            if isinstance(a, dict) and a.get("ticker") and a.get("asset_class"):
                out[a["ticker"].upper()] = a["asset_class"]
    except (OSError, ValueError, KeyError) as e:
        log.debug("watchlist.json read failed: %s", e)

    # Themes — only fill if anchor didn't claim the ticker
    try:
        t = json.loads((base / "asset_themes.json").read_text())
        for _theme_id, theme in t.get("themes", {}).items():
            if not isinstance(theme, dict):
                continue
            cls = theme.get("asset_class") or "uncategorized"
            for tk in theme.get("watchlist_tickers", []) or []:
                k = tk.upper()
                if k not in out:
                    out[k] = cls
    except (OSError, ValueError, KeyError) as e:
        log.debug("asset_themes.json read failed: %s", e)

    _VERTICAL_CACHE = out
    return out


def _vertical_for(ticker: str) -> str:
    return _load_ticker_verticals().get(ticker.upper(), "uncategorized")


# ---------------------------------------------------------------------------
# 1a — closed-trade P&L lens (source_outcomes driven)
# ---------------------------------------------------------------------------

def attribution(
    conn: sqlite3.Connection,
    *,
    window_days: int = 30,
    recency_half_life_days: float | None = None,
    now: datetime | None = None,
    include_meta: bool = False,
) -> list[dict] | dict:
    """Per-source aggregated P&L over the last `window_days`.

    Reads `source_outcomes` rows recorded within the window. Each row
    carries `outcome_pnl_percent` (the realized trade %) and a stored
    `attribution_weight` (how much credit the source got at review
    time — initially 1/N from feedback_writer).

    Recency decay on read
    ─────────────────────
    Beyond the stored weight, this aggregation multiplies each row by
    a recency factor `0.5 ** (age_days / half_life)`. Default half-life
    is `window_days / 2` so the leaderboard naturally prefers fresher
    contributions without dropping older ones entirely. Pass
    `recency_half_life_days=None` to your call site's overriding value,
    or `recency_half_life_days=0` to disable decay (rows count at
    stored weight only).

    Returns rows sorted by `weighted_pnl_pct desc`. Empty (the default
    today, since no trades have closed yet) when the window contains
    no attributed rows. Pass `include_meta=True` to get a dict with a
    `_meta` summary + a `rows` key — useful for surfaces that want to
    explain *why* there's no data ("0 rows in 30d window; check that
    feedback_writer has populated source_outcomes").
    """
    now = now or datetime.now(timezone.utc)
    cutoff_dt = now - timedelta(days=window_days)
    cutoff = cutoff_dt.isoformat()
    half_life = (
        recency_half_life_days
        if recency_half_life_days is not None
        else max(1.0, window_days / 2.0)
    )

    # Quickly count total source_outcomes rows for the empty-data
    # diagnostic (so a fresh DB explains why result is empty).
    total_rows = conn.execute("SELECT COUNT(*) FROM source_outcomes").fetchone()[0]

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
        meta = {
            "lens": "1a_closed_trade",
            "window_days": window_days,
            "recency_half_life_days": half_life,
            "rows_in_table_total": int(total_rows),
            "rows_in_window": 0,
            "n_sources": 0,
            "message": (
                "no source_outcomes rows in window"
                + (" — table is empty (feedback_writer hasn't fired yet)"
                   if total_rows == 0 else
                   f" — table has {total_rows} rows total, but none within"
                   f" the last {window_days}d")
            ),
        }
        log.info("attribution: %s", meta["message"])
        if include_meta:
            return {"_meta": meta, "rows": []}
        return []

    bucket: dict[str, dict] = defaultdict(
        lambda: {
            "n_outcomes": 0,
            "sum_pnl_pct": 0.0,
            "sum_weighted_pnl_pct": 0.0,
            "sum_effective_weight": 0.0,
            "sum_stored_weight": 0.0,
            "last_recorded_at": None,
        }
    )
    for source_id, weight, pnl_pct, recorded_at in rows:
        stored_w = float(weight or 0.0)
        rec_dt = _parse_iso(recorded_at) or now
        age_days = max(0.0, (now - rec_dt).total_seconds() / 86400.0)
        decay = _recency_multiplier(age_days, half_life)
        effective_w = stored_w * decay

        b = bucket[source_id]
        b["n_outcomes"] += 1
        b["sum_pnl_pct"] += float(pnl_pct)
        b["sum_weighted_pnl_pct"] += float(pnl_pct) * effective_w
        b["sum_effective_weight"] += effective_w
        b["sum_stored_weight"] += stored_w
        if not b["last_recorded_at"] or recorded_at > b["last_recorded_at"]:
            b["last_recorded_at"] = recorded_at

    out: list[dict] = []
    for source_id, b in bucket.items():
        n = b["n_outcomes"]
        avg = b["sum_pnl_pct"] / n if n else 0.0
        weighted = (
            b["sum_weighted_pnl_pct"] / b["sum_effective_weight"]
            if b["sum_effective_weight"]
            else 0.0
        )
        out.append(
            {
                "source_id": source_id,
                "n_outcomes": n,
                "total_pnl_pct": round(b["sum_pnl_pct"], 4),
                "avg_pnl_pct": round(avg, 4),
                "weighted_pnl_pct": round(weighted, 4),
                "sum_effective_weight": round(b["sum_effective_weight"], 4),
                "sum_stored_weight": round(b["sum_stored_weight"], 4),
                "last_recorded_at": b["last_recorded_at"],
                "window_days": window_days,
                "recency_half_life_days": half_life,
            }
        )
    out.sort(key=lambda r: r["weighted_pnl_pct"], reverse=True)

    if include_meta:
        return {
            "_meta": {
                "lens": "1a_closed_trade",
                "window_days": window_days,
                "recency_half_life_days": half_life,
                "rows_in_table_total": int(total_rows),
                "rows_in_window": len(rows),
                "n_sources": len(out),
                "message": f"{len(out)} sources across {len(rows)} attributions in the last {window_days}d",
            },
            "rows": out,
        }
    return out


def attribution_30d(conn: sqlite3.Connection) -> list[dict]:
    return attribution(conn, window_days=30)  # type: ignore[return-value]


def attribution_90d(conn: sqlite3.Connection) -> list[dict]:
    return attribution(conn, window_days=90)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Helper for journal/feedback_writer.py — recommended attribution weights
# ---------------------------------------------------------------------------

def recommended_attribution_weights(
    sources_credited: list[str],
    *,
    mention_age_days: dict[str, float] | None = None,
    half_life_days: float = 14.0,
) -> dict[str, float]:
    """Recommend per-source attribution_weight for a single
    `trade_reviews.sources_credited_json` submission.

    Feedback_writer.py default behavior (per the journal-feedback-loop
    brief, v1) is to write `attribution_weight = 1/N` equal-split. This
    helper offers a richer alternative: weight each source by the
    recency of its most-recent supporting mention before the trade was
    opened, then normalize so the weights sum to 1.0.

    Arguments
    ─────────
    sources_credited
        The list from Q2 of the 7-question review modal.
    mention_age_days
        Optional {source_id: age_in_days} captured at trade-open time
        — i.e. how stale was each source's most-recent qualifying
        mention. If missing, the source falls back to half_life_days
        (i.e. weight 0.5 before normalization).
    half_life_days
        Decay half-life. Default 14d matches the working life of a
        macro thesis read against the news cycle.

    Returns
    ─────────
    Dict {source_id: weight} normalized to sum 1.0. If all sources
    have zero contribution (impossible under normal flow), falls back
    to 1/N equal split rather than dividing by zero.

    This helper is OPT-IN — feedback_writer can keep 1/N if it wants;
    the consumption side (`attribution()` above) applies its own
    recency decay regardless of which weights you store.
    """
    if not sources_credited:
        return {}
    ages = mention_age_days or {}
    raw: dict[str, float] = {}
    for sid in sources_credited:
        age = ages.get(sid, half_life_days)
        raw[sid] = _recency_multiplier(age, half_life_days)
    total = sum(raw.values())
    if total <= 0:
        n = len(sources_credited)
        return {sid: 1.0 / n for sid in sources_credited}
    return {sid: w / total for sid, w in raw.items()}


# ---------------------------------------------------------------------------
# 1b — expression trend lens (documents × prices)
# ---------------------------------------------------------------------------

def _load_close_lookup(
    conn: sqlite3.Connection, tickers: set[str]
) -> dict[str, list[tuple[datetime, float]]]:
    """{ticker: [(observed_dt, close), ...]} sorted ascending."""
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


def _close_at_or_before(bars: list[tuple[datetime, float]], target: datetime) -> float | None:
    last: float | None = None
    for dt, close in bars:
        if dt <= target:
            last = close
        else:
            break
    return last


def _close_at_or_after(bars: list[tuple[datetime, float]], target: datetime) -> float | None:
    for dt, close in bars:
        if dt >= target:
            return close
    return None


def _source_tags() -> dict[str, list[str]]:
    try:
        return {
            s.source_id: list(s.routing_tags or s.market_focus or [])
            for s in load_sources(include_archived=True)
        }
    except Exception as e:
        log.debug("load_sources failed: %s", e)
        return {}


def _iter_signals(conn: sqlite3.Connection) -> Iterable[tuple[str, datetime, str, str]]:
    """Yield (source_id, published_dt, document_id, ticker)."""
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


_SORT_MODES = ("decay_weighted", "raw_return")


def signal_attribution(
    conn: sqlite3.Connection,
    *,
    horizons: tuple[int, ...] = (7, 30, 90),
    min_signals: int = 1,
    now: datetime | None = None,
    include_meta: bool = False,
    sort_mode: str = "decay_weighted",
    sort_half_life_days: float = 30.0,
) -> list[dict] | dict:
    """Per-source forward-return rollup across every ticker the source
    has mentioned in any document, regardless of whether a trade was
    taken.

    V2: per-vertical breakdown nested under each horizon.
    V3: decay-aware ordering. `sort_mode` defaults to `decay_weighted`,
        which ranks each source by
            hit_rate × log(1 + n_signals) × recency_decay
        where `recency_decay = 0.5 ** (days_since_last_signal /
        sort_half_life_days)`. This pushes consistently-correct sources
        with fresh activity to the top, and demotes sources that called
        well once a year ago. Pass `sort_mode='raw_return'` to recover
        the v2 sort (just by 30d avg_forward_return_pct desc) for any
        caller that pinned the old ordering.
    """
    if sort_mode not in _SORT_MODES:
        raise ValueError(f"sort_mode must be one of {_SORT_MODES}, got {sort_mode!r}")
    now = now or datetime.now(timezone.utc)

    # Collect signals + tickers we'll need prices for.
    signals: list[tuple[str, datetime, str]] = []
    tickers: set[str] = set()
    for source_id, dt, _doc_id, ticker in _iter_signals(conn):
        signals.append((source_id, dt, ticker))
        tickers.add(ticker)

    n_docs_total = conn.execute(
        "SELECT COUNT(*) FROM documents WHERE cleaned_text IS NOT NULL AND cleaned_text != ''"
    ).fetchone()[0]
    n_prices_total = conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0]

    if not signals:
        meta = {
            "lens": "1b_expression_trend",
            "horizons": list(horizons),
            "n_documents": int(n_docs_total),
            "n_prices_rows": int(n_prices_total),
            "n_signals": 0,
            "message": (
                "no signals extracted"
                + (" — no documents in DB" if n_docs_total == 0 else
                   " — documents present but none mentioned an allow-listed ticker")
            ),
        }
        log.info("signal_attribution: %s", meta["message"])
        if include_meta:
            return {"_meta": meta, "rows": []}
        return []

    closes = _load_close_lookup(conn, tickers)
    tags = _source_tags()

    def _empty_vertical_acc() -> dict:
        return {"n_signals": 0, "n_with_price_data": 0, "sum_ret": 0.0, "n_pos": 0}

    def _empty_horizon_acc() -> dict:
        return {
            "n_with_price_data": 0,
            "sum_ret": 0.0,
            "n_pos": 0,
            "by_vertical": defaultdict(_empty_vertical_acc),
        }

    by_source: dict[str, dict] = {}

    for source_id, dt, ticker in signals:
        bucket = by_source.setdefault(
            source_id,
            {
                "n_signals": 0,
                "horizons": {h: _empty_horizon_acc() for h in horizons},
                "source_verticals": Counter(),   # from sources.json routing_tags
                "ticker_verticals": Counter(),   # from ticker asset_class
                "first_signal_at": None,
                "last_signal_at": None,
            },
        )
        bucket["n_signals"] += 1
        iso = dt.isoformat()
        if not bucket["first_signal_at"] or iso < bucket["first_signal_at"]:
            bucket["first_signal_at"] = iso
        if not bucket["last_signal_at"] or iso > bucket["last_signal_at"]:
            bucket["last_signal_at"] = iso
        for tag in tags.get(source_id, []):
            bucket["source_verticals"][tag] += 1
        vert = _vertical_for(ticker)
        bucket["ticker_verticals"][vert] += 1

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
            vb = hb["by_vertical"][vert]
            vb["n_signals"] += 1
            vb["n_with_price_data"] += 1
            vb["sum_ret"] += ret
            if ret > 0:
                vb["n_pos"] += 1

    out: list[dict] = []
    for source_id, b in by_source.items():
        if b["n_signals"] < min_signals:
            continue
        horizon_rows: dict[int, dict] = {}
        for h, hb in b["horizons"].items():
            n = hb["n_with_price_data"]
            avg = hb["sum_ret"] / n if n else 0.0
            hit = hb["n_pos"] / n if n else 0.0
            verticals_out: dict[str, dict] = {}
            for vert, vb in sorted(
                hb["by_vertical"].items(),
                key=lambda kv: kv[1]["n_with_price_data"],
                reverse=True,
            ):
                vn = vb["n_with_price_data"]
                verticals_out[vert] = {
                    "n_signals": vb["n_signals"],
                    "n_with_price_data": vn,
                    "avg_forward_return_pct": round((vb["sum_ret"] / vn * 100) if vn else 0.0, 4),
                    "hit_rate": round((vb["n_pos"] / vn) if vn else 0.0, 4),
                }
            horizon_rows[h] = {
                "n_with_price_data": n,
                "avg_forward_return_pct": round(avg * 100, 4),
                "hit_rate": round(hit, 4),
                "by_vertical": verticals_out,
            }
        source_verticals = [t for t, _ in b["source_verticals"].most_common(5)]
        out.append(
            {
                "source_id": source_id,
                "n_signals": b["n_signals"],
                "first_signal_at": b["first_signal_at"],
                "last_signal_at": b["last_signal_at"],
                "source_verticals": source_verticals,
                "ticker_verticals": [v for v, _ in b["ticker_verticals"].most_common(5)],
                # Back-compat alias used by desk_data.py before v2 split.
                # Equivalent to source_verticals; keep until that consumer
                # is updated to read the distinct fields.
                "verticals": source_verticals,
                "horizons": horizon_rows,
            }
        )

    def _raw_return_key(row: dict) -> float:
        h = row["horizons"].get(30) or next(iter(row["horizons"].values()), {})
        return h.get("avg_forward_return_pct", 0.0)

    def _decay_weighted_key(row: dict) -> float:
        # Use 30d hit_rate where available, else fall back to whatever
        # horizon has data — we want SOMETHING for sources with no 30d
        # bars yet (e.g., very recent first signal in a 7d-only world).
        h = row["horizons"].get(30) or next(iter(row["horizons"].values()), {})
        hit_rate = float(h.get("hit_rate", 0.0) or 0.0)
        n = max(0, int(row.get("n_signals", 0) or 0))
        last_iso = row.get("last_signal_at")
        last_dt = _parse_iso(last_iso) if last_iso else None
        age_days = max(0.0, (now - last_dt).total_seconds() / 86400.0) if last_dt else 0.0
        decay = _recency_multiplier(age_days, sort_half_life_days)
        # log(1+n) keeps the curve concave: 10 signals ≠ 10× one signal.
        import math as _m
        return hit_rate * _m.log1p(n) * decay

    sort_key = _decay_weighted_key if sort_mode == "decay_weighted" else _raw_return_key

    # Surface the score alongside each row so the dashboard can render
    # "why does this source rank here?" without recomputing.
    if sort_mode == "decay_weighted":
        for r in out:
            r["decay_weighted_score"] = round(_decay_weighted_key(r), 6)

    out.sort(key=sort_key, reverse=True)

    if include_meta:
        return {
            "_meta": {
                "lens": "1b_expression_trend",
                "horizons": list(horizons),
                "n_documents": int(n_docs_total),
                "n_prices_rows": int(n_prices_total),
                "n_signals": len(signals),
                "n_sources": len(out),
                "sort_mode": sort_mode,
                "sort_half_life_days": sort_half_life_days if sort_mode == "decay_weighted" else None,
                "message": f"{len(out)} sources across {len(signals)} signals",
            },
            "rows": out,
        }
    return out


def signal_history(
    conn: sqlite3.Connection,
    source_id: str,
    *,
    horizon: int = 30,
    bucket: str = "month",
) -> list[dict]:
    """Time-series of one source's forward-return performance, bucketed
    by month (default) so dashboards can plot trend up/down."""
    if bucket != "month":
        raise ValueError(f"unsupported bucket: {bucket!r}")

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
        log.info("signal_history(%s): no signals", source_id)
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

"""Mention extraction precision.

Question: when a ticker auto-promotes onto the watchlist via
`mentions:*` origin, does it later score well or produce a trade?

Definition (per ticker):
- Promotion event = first `trade_scores` row whose
  `reasoning_trail_json.watchlist_origins` contains a string starting
  with `mentions:`.
- "Good" if EITHER (a) within `horizon_days` after the promotion, the
  same ticker has another `trade_scores` row with
  `adjusted_total_score >= score_threshold`, OR (b) any `trades` row
  exists for that ticker with entry_date >= promotion date.

precision@k = (#good among top-k by promotion order) / k.
The function also reports the bulk precision (all promotions, not
windowed by k) for context.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone


log = logging.getLogger(__name__)


def _parse_iso(ts: str) -> datetime | None:
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


def _has_mention_origin(reasoning_trail_json: str | None) -> list[str]:
    """Return the list of mentions:* origin strings on this score row.
    Empty if none."""
    if not reasoning_trail_json:
        return []
    try:
        trail = json.loads(reasoning_trail_json)
    except (TypeError, ValueError):
        return []
    origins = trail.get("watchlist_origins", []) or []
    return [o for o in origins if isinstance(o, str) and o.startswith("mentions:")]


def mention_precision(
    conn: sqlite3.Connection,
    *,
    k: int = 10,
    score_threshold: int = 70,
    horizon_days: int = 30,
) -> dict:
    """Precision@k for mention-driven watchlist promotions.

    Empty data (no promotion events) → returns the empty-shaped dict
    rather than raising.
    """
    # Pull every score row with its asset ticker + reasoning trail.
    cur = conn.execute(
        """
        SELECT ts.score_id, ts.scored_at, ts.adjusted_total_score,
               ts.reasoning_trail_json, a.ticker, a.asset_id
        FROM trade_scores ts
        JOIN technical_setups s ON s.setup_id = ts.setup_id
        JOIN assets a ON a.asset_id = s.asset_id
        ORDER BY ts.scored_at ASC
        """
    )
    rows = cur.fetchall()

    # Group by ticker; capture the first mention-promotion event per
    # ticker, plus all later score rows (used for "good" check).
    promotions: dict[str, dict] = {}
    later_scores: dict[str, list[tuple[datetime, int]]] = defaultdict(list)

    for score_id, scored_at, adj_total, trail_json, ticker, _asset_id in rows:
        dt = _parse_iso(scored_at)
        if dt is None:
            continue
        origins = _has_mention_origin(trail_json)
        if origins and ticker not in promotions:
            promotions[ticker] = {
                "ticker": ticker,
                "promoted_at": dt.isoformat(),
                "origins": origins,
                "promoted_score": int(adj_total),
            }
        # Record all scoring observations for downstream "did it score
        # well later?" check.
        later_scores[ticker].append((dt, int(adj_total)))

    if not promotions:
        # Diagnostic: how many score rows exist vs. how many had a
        # mentions:* origin? Lets the dashboard distinguish "no scoring
        # yet" from "scoring is happening but mentions never promoted".
        n_total_scores = conn.execute("SELECT COUNT(*) FROM trade_scores").fetchone()[0]
        if n_total_scores == 0:
            reason = "no trade_scores rows yet — run `score run` to populate"
        else:
            reason = (
                f"{n_total_scores} trade_scores rows exist but none had a "
                "mentions:* origin in reasoning_trail_json.watchlist_origins"
            )
        log.info("mention_precision: %s", reason)
        return {
            "n_promoted": 0,
            "n_good": 0,
            "precision_at_k": 0.0,
            "k": k,
            "score_threshold": score_threshold,
            "horizon_days": horizon_days,
            "ranked_by_promotion": [],
            "_meta": {
                "lens": "mention_precision",
                "n_total_scores": int(n_total_scores),
                "message": reason,
            },
        }

    # Trades by ticker (any trade with entry_date >= promotion satisfies (b)).
    cur2 = conn.execute(
        """
        SELECT a.ticker, t.entry_date
        FROM trades t
        JOIN assets a ON a.asset_id = t.asset_id
        """
    )
    trades_by_ticker: dict[str, list[datetime]] = defaultdict(list)
    for ticker, entry_date in cur2.fetchall():
        dt = _parse_iso(entry_date)
        if dt is not None:
            trades_by_ticker[ticker].append(dt)

    # Classify each promotion.
    classified: list[dict] = []
    for ticker, p in promotions.items():
        promoted_at = _parse_iso(p["promoted_at"])
        horizon_end = promoted_at + timedelta(days=horizon_days)

        # (a) later score ≥ threshold within horizon
        scored_well = any(
            dt > promoted_at and dt <= horizon_end and adj >= score_threshold
            for dt, adj in later_scores.get(ticker, [])
        )
        # (b) trade exists with entry on/after promotion (no horizon cap —
        # a trade ever opening on this ticker validates the promotion)
        traded = any(d >= promoted_at for d in trades_by_ticker.get(ticker, []))
        is_good = bool(scored_well or traded)

        classified.append(
            {
                "ticker": ticker,
                "promoted_at": p["promoted_at"],
                "promoted_score": p["promoted_score"],
                "origins": p["origins"],
                "scored_well_within_horizon": scored_well,
                "traded": traded,
                "good": is_good,
            }
        )

    # Order by promotion time (oldest first) — "k" is read as the first
    # k chronologically, which is the relevant population if we're
    # asking "of what we promoted, how many panned out?".
    classified.sort(key=lambda r: r["promoted_at"])

    n_promoted = len(classified)
    n_good = sum(1 for r in classified if r["good"])
    top_k = classified[:k] if k > 0 else classified
    n_good_in_k = sum(1 for r in top_k if r["good"])
    precision_at_k = n_good_in_k / len(top_k) if top_k else 0.0

    return {
        "n_promoted": n_promoted,
        "n_good": n_good,
        "precision_at_k": round(precision_at_k, 4),
        "precision_overall": round(n_good / n_promoted, 4) if n_promoted else 0.0,
        "k": k,
        "score_threshold": score_threshold,
        "horizon_days": horizon_days,
        "ranked_by_promotion": classified,
    }

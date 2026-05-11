"""Author-level analytics on manual drops.

The manual-input layer writes one `documents` row per drop with:
  - `author_id` (slug into `input_authors`)
  - `user_metadata_json` (`{"user": {"conviction": 1-5, ...}, ...}`)
  - `cleaned_text` (drives mention extraction the same way RSS docs do)

This module gives the learning loop two pivots that signal_attribution
can't:

  R1. `author_attribution(conn, horizons=...)` — same forward-return
      engine as `signal_attribution`, but pivoted on documents.author_id
      instead of source_id. Answers "which named author calls the best
      trades?" — independent of the RSS-source identity that the
      attribution / signal_attribution functions already cover.

  R2. `conviction_calibration(conn, horizons=...)` — buckets every
      mention by the conviction (1-5) the user stamped on the drop and
      reports forward return + hit rate per bucket. Answers "does my
      gut grade my own ideas correctly?".

Both reuse the price-lookup + window helpers in source_attribution.py
so behaviour stays consistent. Both return informative `_meta` blocks
on empty data instead of bare lists, matching v2's pattern.

Field mapping verified against
`src/macro_positioning/manual/processor.py` (commit 2d30c13+):

    INSERT INTO documents (
        ..., author_id, user_metadata_json, ...
    ) VALUES (
        ..., author_id, json.dumps({"user": ManualMetadata, ...}), ...
    )

`ManualMetadata.conviction` is bounded to 1..5 by the validator
(see manual/models.py); we treat anything outside that range as
'unbucketed' here defensively.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Iterable

from macro_positioning.learning.source_attribution import (
    _close_at_or_after,
    _close_at_or_before,
    _load_close_lookup,
    _parse_iso,
    _vertical_for,
)
from macro_positioning.scoring.mention_extractor import extract_tickers_from_text


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared signal generator pivoted on author + conviction
# ---------------------------------------------------------------------------

def _iter_authored_signals(
    conn: sqlite3.Connection,
) -> Iterable[tuple[str, datetime, str, int | None, str]]:
    """Yield (author_id, published_dt, ticker, conviction_or_None, display_name).

    Only emits rows where `documents.author_id` is non-empty. That's the
    intentional filter: this module ignores RSS-style ingestion (which
    leaves author_id NULL); it's exclusively for manual drops.
    """
    cur = conn.execute(
        """
        SELECT d.author_id, d.published_at, d.cleaned_text,
               d.user_metadata_json, COALESCE(a.display_name, d.author)
        FROM documents d
        LEFT JOIN input_authors a ON a.author_id = d.author_id
        WHERE d.author_id IS NOT NULL AND d.author_id != ''
          AND d.cleaned_text IS NOT NULL AND d.cleaned_text != ''
        """
    )
    for author_id, published_at, cleaned_text, user_meta_json, display in cur:
        dt = _parse_iso(published_at)
        if dt is None:
            continue
        conviction: int | None = None
        if user_meta_json:
            try:
                meta = json.loads(user_meta_json)
                u = meta.get("user", {}) if isinstance(meta, dict) else {}
                c = u.get("conviction")
                if isinstance(c, (int, float)):
                    ci = int(c)
                    if 1 <= ci <= 5:
                        conviction = ci
            except (json.JSONDecodeError, AttributeError, TypeError) as e:
                log.debug("user_metadata_json parse failed: %s", e)
        for ticker in extract_tickers_from_text(cleaned_text):
            yield author_id, dt, ticker, conviction, (display or author_id)


# ---------------------------------------------------------------------------
# R1 — Per-author hit-rate aggregator
# ---------------------------------------------------------------------------

def author_attribution(
    conn: sqlite3.Connection,
    *,
    horizons: tuple[int, ...] = (7, 30, 90),
    min_signals: int = 1,
    now: datetime | None = None,
    include_meta: bool = False,
) -> list[dict] | dict:
    """Per-author forward-return rollup across every ticker the author
    has mentioned in any manual drop.

    Returns one row per author with:
      - n_signals, first/last_signal_at
      - display_name (from input_authors.display_name, falls back to
        the document's author column)
      - ticker_verticals: top-5 asset_classes from the actual mentions
      - horizons: {h: {n_with_price_data, hit_rate, avg_forward_return_pct}}

    Empty result if no manual drops yet — with `_meta` summary explaining
    that when `include_meta=True`.
    """
    now = now or datetime.now(timezone.utc)

    signals: list[tuple[str, datetime, str, int | None, str]] = []
    tickers: set[str] = set()
    for row in _iter_authored_signals(conn):
        signals.append(row)
        tickers.add(row[2])

    n_manual_docs = conn.execute(
        "SELECT COUNT(*) FROM documents WHERE author_id IS NOT NULL AND author_id != ''"
    ).fetchone()[0]
    n_authors_total = conn.execute("SELECT COUNT(*) FROM input_authors").fetchone()[0]

    if not signals:
        meta = {
            "lens": "author_attribution",
            "horizons": list(horizons),
            "n_manual_documents": int(n_manual_docs),
            "n_authors_total": int(n_authors_total),
            "n_signals": 0,
            "message": (
                "no author-attributed mentions"
                + (" — no manual drops yet (input_authors is empty too)"
                   if n_manual_docs == 0 and n_authors_total == 0 else
                   f" — {n_manual_docs} manual docs and {n_authors_total} authors exist, "
                   "but none mention an allow-listed ticker")
            ),
        }
        log.info("author_attribution: %s", meta["message"])
        if include_meta:
            return {"_meta": meta, "rows": []}
        return []

    closes = _load_close_lookup(conn, tickers)

    def _empty_horizon_acc() -> dict:
        return {"n_with_price_data": 0, "sum_ret": 0.0, "n_pos": 0}

    by_author: dict[str, dict] = {}
    for author_id, dt, ticker, _conv, display in signals:
        bucket = by_author.setdefault(
            author_id,
            {
                "display_name": display,
                "n_signals": 0,
                "horizons": {h: _empty_horizon_acc() for h in horizons},
                "ticker_verticals": Counter(),
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
        bucket["ticker_verticals"][_vertical_for(ticker)] += 1

        bars = closes.get(ticker, [])
        if not bars:
            continue
        entry = _close_at_or_before(bars, dt)
        if entry is None or entry == 0:
            continue
        from datetime import timedelta
        for h in horizons:
            exit_close = _close_at_or_after(bars, dt + timedelta(days=h))
            if exit_close is None:
                continue
            ret = (exit_close / entry) - 1.0
            hb = bucket["horizons"][h]
            hb["n_with_price_data"] += 1
            hb["sum_ret"] += ret
            if ret > 0:
                hb["n_pos"] += 1

    out: list[dict] = []
    for author_id, b in by_author.items():
        if b["n_signals"] < min_signals:
            continue
        horizon_rows: dict[int, dict] = {}
        for h, hb in b["horizons"].items():
            n = hb["n_with_price_data"]
            horizon_rows[h] = {
                "n_with_price_data": n,
                "avg_forward_return_pct": round((hb["sum_ret"] / n * 100) if n else 0.0, 4),
                "hit_rate": round((hb["n_pos"] / n) if n else 0.0, 4),
            }
        out.append(
            {
                "author_id": author_id,
                "display_name": b["display_name"],
                "n_signals": b["n_signals"],
                "first_signal_at": b["first_signal_at"],
                "last_signal_at": b["last_signal_at"],
                "ticker_verticals": [v for v, _ in b["ticker_verticals"].most_common(5)],
                "horizons": horizon_rows,
            }
        )

    out.sort(
        key=lambda r: (r["horizons"].get(30) or next(iter(r["horizons"].values()), {})).get(
            "avg_forward_return_pct", 0.0
        ),
        reverse=True,
    )

    if include_meta:
        return {
            "_meta": {
                "lens": "author_attribution",
                "horizons": list(horizons),
                "n_manual_documents": int(n_manual_docs),
                "n_authors_total": int(n_authors_total),
                "n_signals": len(signals),
                "n_authors": len(out),
                "message": f"{len(out)} authors across {len(signals)} mentions",
            },
            "rows": out,
        }
    return out


# ---------------------------------------------------------------------------
# R2 — Conviction calibration
# ---------------------------------------------------------------------------

def conviction_calibration(
    conn: sqlite3.Connection,
    *,
    horizons: tuple[int, ...] = (7, 30, 90),
    include_meta: bool = False,
) -> dict:
    """Bucket forward-return outcomes by user-stamped conviction (1-5).

    Question this answers: does a self-rated 5 conviction call
    outperform a self-rated 3?

    Returns dict shape:
      {
        "_meta": { lens, n_signals_total, n_with_conviction, message },
        "horizons": {
            h: {
              "by_conviction": {
                  1: {"n_signals": int, "n_with_price_data": int,
                      "avg_forward_return_pct": float, "hit_rate": float},
                  ...
              },
              "totals": {"n_with_price_data": int, "avg_forward_return_pct", "hit_rate"},
              "monotonic_score": float | None,
                # Spearman ρ between conviction levels and avg returns,
                # using whichever buckets had price data. None if <2
                # populated buckets.
            }
        }
      }

    Buckets without any signals are omitted from `by_conviction` so the
    dashboard can't render a phantom bucket-0 row.
    """
    from datetime import timedelta

    signals = list(_iter_authored_signals(conn))
    n_with_conviction = sum(1 for s in signals if s[3] is not None)

    if not signals:
        n_docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        msg = (
            "no manual drops with mentions yet"
            if n_docs == 0
            else f"{n_docs} documents in DB but none had author_id + an allow-listed ticker"
        )
        log.info("conviction_calibration: %s", msg)
        return {
            "_meta": {
                "lens": "conviction_calibration",
                "n_signals_total": 0,
                "n_with_conviction": 0,
                "message": msg,
            },
            "horizons": {},
        }

    if n_with_conviction == 0:
        msg = (
            f"{len(signals)} author-attributed mentions, but none carry a "
            "user.conviction value in user_metadata_json — manual SPA "
            "drops with conviction unset"
        )
        log.info("conviction_calibration: %s", msg)
        return {
            "_meta": {
                "lens": "conviction_calibration",
                "n_signals_total": len(signals),
                "n_with_conviction": 0,
                "message": msg,
            },
            "horizons": {},
        }

    tickers = {s[2] for s in signals}
    closes = _load_close_lookup(conn, tickers)

    def _empty_bucket() -> dict:
        return {"n_signals": 0, "n_with_price_data": 0, "sum_ret": 0.0, "n_pos": 0}

    # horizons[h][conviction_level] = bucket
    by_h: dict[int, dict[int, dict]] = {h: defaultdict(_empty_bucket) for h in horizons}

    for _author_id, dt, ticker, conviction, _disp in signals:
        if conviction is None:
            continue
        bars = closes.get(ticker, [])
        # Always count the signal at least, so n_signals reflects "how
        # many calls at this conviction did the user make".
        for h in horizons:
            by_h[h][conviction]["n_signals"] += 1
        if not bars:
            continue
        entry = _close_at_or_before(bars, dt)
        if entry is None or entry == 0:
            continue
        for h in horizons:
            exit_close = _close_at_or_after(bars, dt + timedelta(days=h))
            if exit_close is None:
                continue
            ret = (exit_close / entry) - 1.0
            b = by_h[h][conviction]
            b["n_with_price_data"] += 1
            b["sum_ret"] += ret
            if ret > 0:
                b["n_pos"] += 1

    horizons_out: dict[int, dict] = {}
    for h, buckets in by_h.items():
        by_conv: dict[int, dict] = {}
        total_n = 0
        total_sum = 0.0
        total_pos = 0
        # Sort 1..5 for stable output
        for lvl in sorted(buckets.keys()):
            b = buckets[lvl]
            n = b["n_with_price_data"]
            by_conv[lvl] = {
                "n_signals": b["n_signals"],
                "n_with_price_data": n,
                "avg_forward_return_pct": round((b["sum_ret"] / n * 100) if n else 0.0, 4),
                "hit_rate": round((b["n_pos"] / n) if n else 0.0, 4),
            }
            total_n += n
            total_sum += b["sum_ret"]
            total_pos += b["n_pos"]
        # Monotonic score: Spearman ρ between conviction and avg return
        # across buckets that had price data. Tiny populations are noisy
        # so we only compute when ≥2 buckets have data.
        populated = [
            (lvl, by_conv[lvl]["avg_forward_return_pct"])
            for lvl in by_conv
            if by_conv[lvl]["n_with_price_data"] > 0
        ]
        monotonic: float | None = None
        if len(populated) >= 2:
            from macro_positioning.learning.score_outcome_correlation import _spearman
            xs = [p[0] for p in populated]
            ys = [p[1] for p in populated]
            res = _spearman(xs, ys)
            monotonic = res.get("spearman")
        horizons_out[h] = {
            "by_conviction": by_conv,
            "totals": {
                "n_with_price_data": total_n,
                "avg_forward_return_pct": round((total_sum / total_n * 100) if total_n else 0.0, 4),
                "hit_rate": round((total_pos / total_n) if total_n else 0.0, 4),
            },
            "monotonic_score": monotonic,
        }

    return {
        "_meta": {
            "lens": "conviction_calibration",
            "n_signals_total": len(signals),
            "n_with_conviction": n_with_conviction,
            "message": f"{n_with_conviction} of {len(signals)} mentions carry a conviction rating",
        },
        "horizons": horizons_out,
    }

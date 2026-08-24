"""Daily FREE ingestion + refresh — no paid LLM calls.

Keeps the data-health board green without touching Anthropic credits:
  ingest   → Google News, Substack, Podcasts (metadata), Gmail newsletters
  insiders → all public SEC/gov/social scrapers (pull_all)
  market   → FRED incremental refresh, yfinance prices
  free ML  → insider signal extraction (heuristic, no LLM), scoring pass

The paid prose/chart LLM signal extraction is deliberately NOT run here —
that stays a manual, budgeted decision (see run_scoring/signals docs).

Run:  uv run python -m scripts.daily_free_ingest    (or scripts/daily_free_ingest.py)
Scheduled via ~/Library/LaunchAgents/com.macro.free-ingest.plist
"""
from __future__ import annotations

import logging
import sqlite3
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("daily_free_ingest")


def _step(name, fn):
    t = time.time()
    try:
        result = fn()
        log.info("STEP OK  %-10s %.1fs  %s", name, time.time() - t, result)
        return {"status": "ok", "result": result}
    except Exception as e:  # noqa: BLE001
        log.exception("STEP FAIL %s", name)
        return {"status": "error", "error": str(e)}


def main() -> int:
    from macro_positioning.core.settings import settings
    from macro_positioning.db.repository import SQLiteRepository
    from macro_positioning.db.schema import initialize_database
    from macro_positioning.ingestion.base import normalize_document

    initialize_database(settings.sqlite_path)
    repo = SQLiteRepository(settings.sqlite_path)

    def _persist(docs):
        n = 0
        for d in docs:
            try:
                repo.save_document(normalize_document(d))
                n += 1
            except Exception:  # noqa: BLE001
                log.debug("save_document failed", exc_info=True)
        return n

    summary: dict[str, dict] = {}

    # --- Ingestion (free RSS + Gmail) ---
    def _news():
        from macro_positioning.ingestion import google_news_rss as g
        docs = g.fetch_all_macro_topics(max_items_per_topic=10)
        return f"{_persist(docs)}/{len(docs)} persisted"
    summary["news"] = _step("news", _news)

    def _substack():
        from macro_positioning.ingestion import substack as s
        docs = s.fetch_all(max_items_per_feed=10)
        return f"{_persist(docs)}/{len(docs)} persisted"
    summary["substack"] = _step("substack", _substack)

    def _podcasts():
        from macro_positioning.ingestion import podcast_rss as p
        docs = []
        for src in p.PODCAST_SOURCES:
            try:
                docs.extend(p.fetch_podcast(src.source_id, max_items=4, transcribe=False))
            except Exception:  # noqa: BLE001
                log.debug("podcast fetch failed %s", src.source_id, exc_info=True)
        return f"{_persist(docs)}/{len(docs)} persisted"
    summary["podcasts"] = _step("podcasts", _podcasts)

    def _gmail():
        from macro_positioning.ingestion import personal_gmail as pg
        res = pg.fetch_and_persist(days=2, max_messages=100)
        return f"{res.get('new_documents', 0)} new"
    summary["gmail"] = _step("gmail", _gmail)

    # --- Insiders (public disclosures, free) ---
    def _insiders():
        from macro_positioning.insiders import cli
        res = cli.pull_all(catch_errors=True)
        total = sum(v.get("ingested", 0) for v in res.values())
        return f"{total} events across {len(res)} sources"
    summary["insiders"] = _step("insiders", _insiders)

    # --- Market data (free) ---
    def _fred():
        from macro_positioning.market.fred_history import incremental_refresh
        from macro_positioning.market.fred_provider import ALL_SERIES, FREDMarketDataProvider
        if not settings.fred_api_key:
            return "skipped (no key)"
        prov = FREDMarketDataProvider()
        with sqlite3.connect(settings.sqlite_path) as c:
            counts = incremental_refresh(prov, c, ALL_SERIES.keys(), window_days=21)
        return f"{sum(counts.values())} rows / {len(counts)} series"
    summary["fred"] = _step("fred", _fred)

    def _prices():
        from macro_positioning.prices.fetcher import fetch_and_persist
        from macro_positioning.scoring.watchlist_resolver import resolve_watchlist
        resolved = resolve_watchlist(framework_regime="commodity_led_inflation")
        tickers = {e.ticker for e in resolved.entries}
        with sqlite3.connect(settings.sqlite_path) as c:
            for (t,) in c.execute(
                "SELECT DISTINCT asset_ticker FROM signals "
                "WHERE extracted_at >= datetime('now','-30 day')"
            ).fetchall():
                if t:
                    tickers.add(str(t).upper())
        pr = fetch_and_persist(sorted(tickers), days=200)
        return f"{pr.tickers_with_data}/{pr.tickers_requested} tickers, {pr.bars_persisted} bars"
    summary["prices"] = _step("prices", _prices)

    # --- Free downstream (heuristic signals + deterministic scoring) ---
    def _insider_signals():
        from macro_positioning.signals.runner import extract_pending
        s = extract_pending(limit=500, since_days=21, extractor_filter="insider_extractor")
        return f"{s.signals_written} signals"
    summary["insider_signals"] = _step("insider_signals", _insider_signals)

    def _scoring():
        from macro_positioning.scoring.runner import run_scoring_pass
        # pass_kind='scheduled' is what makes this pass alertable — the
        # alerts evaluator ignores hand-run and what-if passes so it never
        # compares across two different regime assumptions.
        s = run_scoring_pass(pass_kind="scheduled")
        return f"{s.persisted} scored"
    summary["scoring"] = _step("scoring", _scoring)

    # Alerts ride on the scoring pass above: the twice-daily run gets the
    # same notification treatment as the hourly watcher, so a state change
    # here isn't silently waiting for the next :00.
    def _alerts():
        from macro_positioning.alerts import run_alert_cycle
        r = run_alert_cycle()
        return f"{r['derived']} derived, {r['delivered']} delivered"
    summary["alerts"] = _step("alerts", _alerts)

    def _regime_snapshot():
        from macro_positioning.regime.snapshots import record_daily_regime_snapshot
        with sqlite3.connect(settings.sqlite_path) as c:
            res = record_daily_regime_snapshot(c, seed_history=True)
        return f"{res['regime']} ({res['today']}), backfilled {res['backfilled']}"
    summary["regime_snapshot"] = _step("regime_snapshot", _regime_snapshot)

    errors = [k for k, v in summary.items() if v["status"] == "error"]
    log.info("daily_free_ingest complete — %d/%d ok%s",
             len(summary) - len(errors), len(summary),
             f", errors: {errors}" if errors else "")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

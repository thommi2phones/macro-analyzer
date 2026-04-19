"""Scheduled refresh loop — daily ingest + pipeline + memo generation.

Run as:
  python -m macro_positioning.ingestion.scheduler --once        # single run
  python -m macro_positioning.ingestion.scheduler --cron        # stay running
  python -m macro_positioning.ingestion.scheduler --morning     # morning only

Cron cadence (defaults):
  07:00  — fetch overnight newsletters + news, run brain, generate memo
  12:00  — refresh FRED data + mid-day news
  16:30  — post-close recap: refresh charts, reconcile positions
  Sun    — weekly review: aggregate thesis performance, source scoring

TODO(stream-a):
  1. Use `apscheduler` (add to deps) for cron-style scheduling
  2. Each scheduled task should log start/end with duration + summary
  3. Failures should not kill the scheduler — log and continue
  4. Post results to dashboard /api/scheduler/runs endpoint
"""

from __future__ import annotations

import argparse
import logging
from datetime import UTC, datetime

from macro_positioning.pipelines.run_pipeline import build_pipeline

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scheduled tasks
# ---------------------------------------------------------------------------

def morning_run() -> dict:
    """07:00 daily — overnight newsletter ingest + full pipeline + memo.

    Steps:
      1. fetch_and_persist() personal Gmail newsletters
      2. Fetch Google News RSS for all macro topics
      3. Fetch Finnhub general news
      4. Run full pipeline (includes FRED data fresh)
      5. Generate morning memo
      6. If a thesis crossed a high-conviction threshold, fire alert
    """
    logger.info("=== MORNING RUN START %s ===", datetime.now(UTC).isoformat())

    summary = {
        "timestamp": datetime.now(UTC).isoformat(),
        "steps": {},
    }

    try:
        # TODO(stream-a): wire personal_gmail.fetch_and_persist()
        summary["steps"]["gmail"] = {"status": "pending_impl"}

        # TODO(stream-a): wire google_news_rss.fetch_all_macro_topics()
        summary["steps"]["google_news"] = {"status": "pending_impl"}

        # Run pipeline — this already works
        pipeline = build_pipeline()
        result = pipeline.run([])  # No new docs in stub, just validates infra
        summary["steps"]["pipeline"] = {
            "documents_ingested": result.documents_ingested,
            "theses_extracted": result.theses_extracted,
            "memo_id": result.memo_id,
        }
    except Exception as e:
        logger.error("Morning run failed: %s", e, exc_info=True)
        summary["error"] = str(e)

    logger.info("=== MORNING RUN END ===")
    return summary


def midday_refresh() -> dict:
    """12:00 — quick FRED + mid-day news refresh.

    TODO(stream-a): subset of morning_run, just FRED observations + a light
    pipeline pass.
    """
    logger.info("=== MIDDAY REFRESH ===")
    return {"status": "pending_impl"}


def post_close_recap() -> dict:
    """16:30 — EOD reconciliation + position review.

    TODO(stream-a):
      - Hit Trading-Agent /events/latest for recent trade activity
      - Cross-reference against morning memo predictions
      - Update source scoring based on any closed trades
      - Generate EOD snapshot
    """
    logger.info("=== POST-CLOSE RECAP ===")
    return {"status": "pending_impl"}


def weekly_review() -> dict:
    """Sunday — thesis outcome attribution + source weight recalibration.

    TODO(stream-a):
      - Pull all outcomes from the last 7 days
      - Compute win rate per source
      - Adjust trust weights in source_weights table
      - Generate weekly review memo
    """
    logger.info("=== WEEKLY REVIEW ===")
    return {"status": "pending_impl"}


# ---------------------------------------------------------------------------
# Scheduler runner
# ---------------------------------------------------------------------------

def run_cron() -> None:
    """Start the APScheduler loop. Blocks the process.

    TODO(stream-a): add apscheduler to deps, then:
      from apscheduler.schedulers.blocking import BlockingScheduler
      sched = BlockingScheduler(timezone="America/Los_Angeles")
      sched.add_job(morning_run, 'cron', hour=7, minute=0)
      sched.add_job(midday_refresh, 'cron', hour=12, minute=0)
      sched.add_job(post_close_recap, 'cron', hour=16, minute=30)
      sched.add_job(weekly_review, 'cron', day_of_week='sun', hour=9)
      sched.start()
    """
    raise NotImplementedError("Stream A: add apscheduler")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run morning_run once and exit")
    parser.add_argument("--morning", action="store_true", help="Run morning_run")
    parser.add_argument("--midday", action="store_true", help="Run midday_refresh")
    parser.add_argument("--close", action="store_true", help="Run post_close_recap")
    parser.add_argument("--weekly", action="store_true", help="Run weekly_review")
    parser.add_argument("--cron", action="store_true", help="Start cron scheduler")
    args = parser.parse_args()

    if args.cron:
        run_cron()
    elif args.morning or args.once:
        print(morning_run())
    elif args.midday:
        print(midday_refresh())
    elif args.close:
        print(post_close_recap())
    elif args.weekly:
        print(weekly_review())
    else:
        parser.print_help()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()

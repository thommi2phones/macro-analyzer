"""One-time prose/text signal backfill via Anthropic.

Runs ONLY llm_extractor (never vision) across the pending queue, so:
  - prose docs (news, gmail, substack, podcasts, manual notes) → thesis signals
  - chart-caption docs → caption thesis (their locked vision extraction is
    untouched; llm just reads the KOL's caption text)
Insider docs route to insider_extractor and are skipped by the filter.

record_attempt() marks each doc, so this is resumable — re-running skips
docs already extracted. Progress logged per chunk.
"""
from __future__ import annotations

import logging
import sqlite3
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("backfill_prose")


def main() -> int:
    from macro_positioning.core.settings import settings
    # n8n/gemini/ollama unavailable → force Anthropic for the backfill.
    settings.brain_primary_backend = "anthropic"
    log.info("backend=%s model=%s", settings.brain_primary_backend, settings.claude_model)

    from macro_positioning.signals.runner import extract_pending

    def _sig_count():
        with sqlite3.connect(settings.sqlite_path) as c:
            return c.execute("SELECT COUNT(*) FROM signals").fetchone()[0]

    start_sig = _sig_count()
    t0 = time.time()
    # Single pass over the whole pending queue. Insider/deferred docs are
    # skipped inline by the llm filter; every prose + chart-caption doc runs
    # once. record_attempt() persists each result as it goes, so a crash
    # mid-run is resumable — re-running excludes already-attempted docs.
    s = extract_pending(limit=8000, since_days=21, extractor_filter="llm_extractor")
    d = s.to_dict()
    total_new = _sig_count() - start_sig
    log.info(
        "BACKFILL COMPLETE: seen=%d with_signals=%d no_signal=%d error=%d "
        "signals_written=%d (net new=%d) in %.0fs",
        d["docs_seen"], d["docs_with_signals"], d["docs_no_signal"], d["docs_error"],
        d["signals_written"], total_new, time.time() - t0,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Retire duplicate `signals` rows left behind by uuid-keyed inserts.

Before signal_id became content-derived (see Signal.stable_id), every
extraction pass wrote fresh rows: overlapping `extract_pending()` runs and
re-extracts stored the same call two or three times. Those copies are all
`status='active'`, so aggregation counts each of them — inflating
conviction and the per-author/source counts behind it.

This script finds groups of active rows that are the same call by the
natural key — same document, same extractor, same instrument, same side,
same level set — keeps the earliest (the original observation) and marks
the rest `superseded`, pointing at the keeper.

Nothing is deleted. `--apply` is required to write; the default run only
reports. Point `--db` at a copy first if you want to see the effect on
downstream scores before touching the live file.

    python scripts/supersede_duplicate_signals.py            # report only
    python scripts/supersede_duplicate_signals.py --apply
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from macro_positioning.core.settings import settings  # noqa: E402


# The natural key. Levels are part of it: a chart carrying two setups
# yields two rows that differ only by their level set, and both are real.
_KEY_SQL = """
    SELECT signal_id, document_id, extractor_name, asset_ticker, side,
           IFNULL(entry_zone_low, 'x')  AS ez_lo,
           IFNULL(entry_zone_high, 'x') AS ez_hi,
           IFNULL(stop_loss, 'x')       AS stop,
           IFNULL(target_1, 'x')        AS t1,
           IFNULL(target_2, 'x')        AS t2,
           extracted_at, extraction_run_id
    FROM signals
    WHERE status = 'active'
    ORDER BY extracted_at
"""


def find_duplicates(conn: sqlite3.Connection) -> dict[tuple, list[sqlite3.Row]]:
    groups: dict[tuple, list[sqlite3.Row]] = defaultdict(list)
    for r in conn.execute(_KEY_SQL):
        key = (r["document_id"], r["extractor_name"], r["asset_ticker"],
               r["side"], r["ez_lo"], r["ez_hi"], r["stop"], r["t1"], r["t2"])
        groups[key].append(r)
    return {k: v for k, v in groups.items() if len(v) > 1}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=settings.sqlite_path,
                    help="database to operate on (default: the configured one)")
    ap.add_argument("--apply", action="store_true",
                    help="write the status changes (default: report only)")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"no database at {args.db}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")

    dupes = find_duplicates(conn)
    excess = sum(len(v) - 1 for v in dupes.values())
    by_extractor: dict[str, int] = defaultdict(int)
    by_ticker: dict[str, int] = defaultdict(int)
    cross_run = same_run = 0
    for rows in dupes.values():
        by_extractor[rows[0]["extractor_name"]] += len(rows) - 1
        by_ticker[rows[0]["asset_ticker"]] += len(rows) - 1
        if len({r["extraction_run_id"] for r in rows}) > 1:
            cross_run += len(rows) - 1
        else:
            same_run += len(rows) - 1

    active = conn.execute(
        "SELECT COUNT(*) FROM signals WHERE status='active'").fetchone()[0]
    print(f"{len(dupes)} duplicate groups · {excess} rows to retire "
          f"({100 * excess / active:.1f}% of {active} active)")
    print(f"  across runs: {cross_run} · within one run: {same_run}")
    print("  by extractor: " + ", ".join(
        f"{k} {v}" for k, v in sorted(by_extractor.items(), key=lambda kv: -kv[1])))
    top = sorted(by_ticker.items(), key=lambda kv: -kv[1])[:10]
    print("  top tickers:  " + ", ".join(f"{k} {v}" for k, v in top))

    if not args.apply:
        print("\ndry run — nothing written. Re-run with --apply to retire them.")
        return 0

    stamp = datetime.now(UTC).isoformat()
    retired = 0
    with conn:
        for rows in dupes.values():
            keeper, *losers = rows          # earliest wins: it's the original read
            for loser in losers:
                conn.execute(
                    "UPDATE signals SET status='superseded', superseded_by=? "
                    "WHERE signal_id=? AND status='active'",
                    (keeper["signal_id"], loser["signal_id"]),
                )
                retired += 1
    print(f"\nretired {retired} rows at {stamp} (kept {len(dupes)} originals)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

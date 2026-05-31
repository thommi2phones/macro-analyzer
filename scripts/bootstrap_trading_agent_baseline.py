"""One-shot import of the trading_agent's analyzed chart corpus.

Reads `trade_history.json` (328 records, hand-reviewed by Codex against the
trading_agent's chart-analysis framework) and creates one `documents` row
per record, attaching the matching baseline_seed image and writing the
TradeRecord JSON into `extracted_features_json`. All rows are attributed
to a synthetic author "archive:trading_agent_baseline" so they don't
pollute the per-author hit-rate analytics on the real six sources.

Idempotent: stable document_ids are derived from the image filename, so
re-running the script skips already-imported rows. Safe to re-run after
mid-run interruptions or partial failures.

Run:
    uv run python scripts/bootstrap_trading_agent_baseline.py
    uv run python scripts/bootstrap_trading_agent_baseline.py --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

# Allow `python scripts/...` invocation without uv-installed package.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from macro_positioning.core.settings import settings  # noqa: E402
from macro_positioning.db.schema import initialize_database  # noqa: E402
from macro_positioning.manual.authors import upsert_author  # noqa: E402
from macro_positioning.manual.models import AuthorRef  # noqa: E402


TRADE_HISTORY_PATH = Path(
    "/Users/thom/Documents/Personal/Code Projects/trading_agent/data/trade_history.json"
)
# baseline_seed/ is gitignored (142MB of binaries) and lives in the main
# repo checkout, not the worktree. Search both — first hit wins.
_BASELINE_CANDIDATES = [
    _REPO_ROOT / "manual_entry" / "baseline_seed",
    Path("/Users/thom/Documents/Personal/Code Projects/Macro Analyzer/manual_entry/baseline_seed"),
]
BASELINE_DIR = next((p for p in _BASELINE_CANDIDATES if p.is_dir()),
                    _BASELINE_CANDIDATES[0])

# Synthetic author for the historical corpus. Slug must match what
# upsert_author would produce so the foreign-key join lines up.
ARCHIVE_AUTHOR = AuthorRef(
    display_name="trading_agent_baseline",
    channel="archive",
    channel_type="other",
    notes="Synthetic source for the 328 pre-analyzed charts imported from "
          "trading_agent/data/trade_history.json (Codex-reviewed).",
)


def _normalize_filename(name: str) -> str:
    """Match trade_history image_paths to baseline_seed files.

    trade_history JSON uses Unicode narrow-no-break-space (U+202F) between
    the time and AM/PM in macOS screenshot filenames; the actual files on
    disk use a regular space. NFC + NBSP collapse handles both.
    """
    s = unicodedata.normalize("NFC", name)
    return s.replace(" ", " ").replace(" ", " ").strip()


def _stable_document_id(image_filename: str) -> str:
    """Deterministic id keyed on the image filename so re-imports dedupe."""
    h = hashlib.sha256(_normalize_filename(image_filename).encode("utf-8"))
    return "archive-" + h.hexdigest()[:24]


def _build_extracted_features(record: dict) -> dict:
    """Strip the local image_path (trading_agent's filesystem) — the new
    attachment_path field is the canonical reference. Everything else is
    preserved verbatim."""
    out = dict(record)
    out.pop("image_path", None)
    out["imported_from"] = "trading_agent/data/trade_history.json"
    out["imported_at"] = datetime.now(UTC).isoformat()
    return out


def _build_tags_payload(record: dict) -> dict:
    """Match the shape /api/manual/ingest writes so downstream code is
    blind to whether a row came from a live drop or this bootstrap."""
    ticker = (record.get("ticker") or "").strip()
    return {
        "tags": sorted({"manual", "chart", "archive"} | (
            {"crypto"} if "/" in ticker or "USD" in ticker else set()
        )),
        "agents": [
            "narrative_synthesizer",
            "regime_classifier",
            "sector_theme_scorer",
            "technical_scorer",
        ],
        # Already analyzed; the pending_vision drainer should skip these.
        "pending_vision": False,
        "tickers": [ticker] if ticker else [],
        "source": "trading_agent_baseline",
    }


def _build_user_metadata(record: dict) -> dict:
    """Same shape as ManualMetadata so the inbox history view renders
    these alongside live drops."""
    direction = (record.get("direction") or "").upper()
    side = "LONG" if direction == "LONG" else "SHORT" if direction == "SHORT" else None
    tf = (record.get("timeframe") or "").upper().replace(" ", "")
    if tf in ("60", "1H"):
        tf_canonical = "1H"
    elif tf in ("240", "4H"):
        tf_canonical = "4H"
    elif tf in ("D", "DAY", "1D"):
        tf_canonical = "1D"
    elif tf in ("W", "WEEK", "1W"):
        tf_canonical = "1W"
    else:
        tf_canonical = None
    user = {
        "ticker": record.get("ticker"),
        "side": side,
        "conviction": record.get("confluence_score"),
        "timeframe": tf_canonical,
        "note": (record.get("notes") or "")[:280] or None,
    }
    return {
        "user": user,
        "resolved": user,
        "channel": ARCHIVE_AUTHOR.channel,
        "channel_type": ARCHIVE_AUTHOR.channel_type,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be imported, no DB writes.")
    parser.add_argument("--trade-history", type=Path,
                        default=TRADE_HISTORY_PATH,
                        help="Path to trade_history.json")
    parser.add_argument("--baseline-dir", type=Path, default=BASELINE_DIR,
                        help="Directory of baseline chart images")
    parser.add_argument("--limit", type=int, default=0,
                        help="Limit records imported (0 = all)")
    args = parser.parse_args()

    if not args.trade_history.exists():
        print(f"trade_history not found: {args.trade_history}", file=sys.stderr)
        return 2
    if not args.baseline_dir.is_dir():
        print(f"baseline_dir not found: {args.baseline_dir}", file=sys.stderr)
        return 2

    initialize_database(settings.sqlite_path)
    author_id = upsert_author(ARCHIVE_AUTHOR)
    print(f"author_id: {author_id}")

    seed_files = {p.name for p in args.baseline_dir.iterdir() if p.is_file()}
    seed_norm_to_raw = {_normalize_filename(n): n for n in seed_files}

    records = json.loads(args.trade_history.read_text(encoding="utf-8"))
    if args.limit:
        records = records[: args.limit]

    stats = {"total": len(records), "imported": 0, "skipped_existing": 0,
             "skipped_no_image": 0, "skipped_invalid": 0}
    base_dir = settings.base_dir.resolve()

    with sqlite3.connect(settings.sqlite_path) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        for r in records:
            try:
                ip = r.get("image_path") or ""
                norm_name = _normalize_filename(Path(ip).name)
                if not norm_name or norm_name not in seed_norm_to_raw:
                    stats["skipped_no_image"] += 1
                    continue
                actual_filename = seed_norm_to_raw[norm_name]
                abs_image = (args.baseline_dir / actual_filename).resolve()
                try:
                    rel_path = str(abs_image.relative_to(base_dir))
                except ValueError:
                    # baseline_dir outside base_dir — store absolute path.
                    rel_path = str(abs_image)

                document_id = _stable_document_id(actual_filename)

                exists = conn.execute(
                    "SELECT 1 FROM documents WHERE document_id=?",
                    (document_id,),
                ).fetchone()
                if exists:
                    stats["skipped_existing"] += 1
                    continue

                ticker = (r.get("ticker") or "").strip()
                direction = (r.get("direction") or "").upper()
                title = " · ".join(b for b in [ticker, direction, "archive"] if b)
                published_at = r.get("entry_date") or r.get("extracted_at") or \
                    datetime.now(UTC).isoformat()
                tags_payload = _build_tags_payload(r)
                user_meta = _build_user_metadata(r)
                features = _build_extracted_features(r)

                if args.dry_run:
                    stats["imported"] += 1
                    continue

                conn.execute(
                    """
                    INSERT INTO documents (
                        document_id, source_id, title, url, published_at,
                        author, content_type, raw_text, cleaned_text,
                        tags_json, ingested_at, author_id,
                        user_metadata_json, attachment_path,
                        extracted_features_json, attachment_paths_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        f"manual:{author_id}",
                        title or "archive chart",
                        None,
                        published_at,
                        ARCHIVE_AUTHOR.display_name,
                        "manual_chart",
                        r.get("notes") or "",
                        r.get("notes") or "",
                        json.dumps(tags_payload),
                        datetime.now(UTC).isoformat(),
                        author_id,
                        json.dumps(user_meta),
                        rel_path,
                        json.dumps(features),
                        json.dumps([rel_path]),
                    ),
                )
                stats["imported"] += 1
            except Exception as e:
                print(f"  skip (error): {e}", file=sys.stderr)
                stats["skipped_invalid"] += 1
        if not args.dry_run:
            conn.commit()

    print(f"\n=== summary{' (dry-run)' if args.dry_run else ''} ===")
    for k, v in stats.items():
        print(f"  {k:24s} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

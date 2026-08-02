"""Bulk-import a folder of chart screenshots into the manual-input layer.

For each image in the folder:
  1. Compute sha256 of bytes — used for idempotent dedupe.
  2. Run the heuristic OCR fast-path (pytesseract) to pull author /
     channel / ticker / timeframe from any Telegram "Forwarded from:" or
     TradingView header overlay in the screenshot. If found, attribute
     the document to that author (matched against the seeded list); else
     fall back to --default-author.
  3. Copy the image into uploads/charts/YYYY-MM/{uuid}.{ext}.
  4. Insert a `documents` row with pending_vision=true.
  5. Optionally drain pending_vision through Claude Sonnet in the same run.

Designed for the "I have 300 Telegram screenshots" case. Re-running on
the same folder is safe — duplicates (same image bytes) are skipped.

Usage examples:
    # See what would happen, no DB writes:
    uv run python scripts/bulk_import_screenshots.py \\
        --dir ~/Desktop/tg-export/photos --default-author Big_Nuts --dry-run

    # Import + queue for later drain:
    uv run python scripts/bulk_import_screenshots.py \\
        --dir ~/Desktop/tg-export/photos --default-author Big_Nuts

    # Import + analyze inline (slow, ~20s/image, ~$0.001/image):
    uv run python scripts/bulk_import_screenshots.py \\
        --dir ~/Desktop/tg-export/photos --default-author Big_Nuts --analyze
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from macro_positioning.core.settings import settings  # noqa: E402
from macro_positioning.db.schema import initialize_database  # noqa: E402
from macro_positioning.ingestion.pre_tagger import detect_tags, route_to_agents  # noqa: E402
from macro_positioning.manual.authors import slugify_author, upsert_author  # noqa: E402
from macro_positioning.manual.heuristic_ocr import analyze_image as ocr_image  # noqa: E402
from macro_positioning.manual.models import AuthorRef  # noqa: E402


# Common image extensions tesseract / Pillow can read.
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif", ".heic"}


def _iter_images(folder: Path) -> list[Path]:
    """All images directly in folder + subfolders, sorted for stable order."""
    return sorted(
        p for p in folder.rglob("*")
        if p.is_file() and p.suffix.lower() in _IMAGE_EXTS
    )


def _resolve_author(
    *,
    ocr_channel: Optional[str],
    ocr_channel_type: Optional[str],
    ocr_author: Optional[str],
    default_author: AuthorRef,
    known_authors: dict[str, dict],
) -> AuthorRef:
    """Pick the best author for this screenshot.

    Match logic (in order):
      1. OCR'd 'Forwarded from: X' channel → match against seeded
         channels (Feather Hands → Big_Nuts/MadDog31, Stock Unlocked → …).
         Without a person we attribute to the channel itself (e.g.
         "Stock Unlocked" as the source).
      2. OCR'd TradingView header author → attribute to that author with
         channel inherited from default_author (since we don't know the
         delivery venue from a TV chart alone).
      3. Default author passed via --default-author.
    """
    if ocr_channel:
        # Look for a seeded author whose channel matches (case-insensitive).
        match = None
        for a in known_authors.values():
            if (a.get("channel") or "").strip().lower() == ocr_channel.strip().lower():
                match = a
                break
        if match:
            return AuthorRef(
                display_name=match["display_name"],
                channel=match.get("channel"),
                channel_type=match.get("channel_type") or ocr_channel_type or "telegram",
            )
        # Channel detected but no seed match — use channel as both author + channel.
        return AuthorRef(
            display_name=ocr_channel,
            channel=ocr_channel,
            channel_type=ocr_channel_type or "telegram",
        )

    if ocr_author:
        return AuthorRef(
            display_name=ocr_author,
            channel=default_author.channel,
            channel_type=default_author.channel_type,
        )

    return default_author


def _save_attachment(image_bytes: bytes, original_name: str, base_dir: Path) -> tuple[str, Path]:
    """Copy bytes into uploads/charts/YYYY-MM/{uuid}.{ext}, return (rel_path, abs_path)."""
    ext = Path(original_name).suffix.lower() or ".png"
    sub = base_dir / "uploads" / "charts" / datetime.now(UTC).strftime("%Y-%m")
    sub.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    abs_path = sub / name
    abs_path.write_bytes(image_bytes)
    try:
        rel = str(abs_path.relative_to(base_dir))
    except ValueError:
        rel = str(abs_path)
    return rel, abs_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", required=True, type=Path,
                    help="Folder of chart screenshots (recurses).")
    ap.add_argument("--default-author", required=True,
                    help='Display name to attribute when OCR cant detect the source '
                         '(must exist in input_authors OR will be created). '
                         'Example: "Big_Nuts" "Stock Unlocked" "Me".')
    ap.add_argument("--default-channel", default=None,
                    help="Channel/group for --default-author when creating a new row.")
    ap.add_argument("--default-channel-type", default="telegram",
                    help="self|telegram|discord|twitter|other (default: telegram).")
    ap.add_argument("--analyze", action="store_true",
                    help="Run Claude vision inline on each imported doc (~20s/image).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Don't write to DB or copy files — just report.")
    ap.add_argument("--limit", type=int, default=0,
                    help="Cap how many images to process (0 = all).")
    args = ap.parse_args()

    folder = args.dir.expanduser().resolve()
    if not folder.is_dir():
        print(f"folder not found: {folder}", file=sys.stderr)
        return 2

    initialize_database(settings.sqlite_path)
    base_dir = settings.base_dir.resolve()

    default_author = AuthorRef(
        display_name=args.default_author,
        channel=args.default_channel,
        channel_type=args.default_channel_type,
    )
    default_author_id = upsert_author(default_author) if not args.dry_run else slugify_author(default_author)

    # Snapshot the seeded/known authors so OCR can map "Forwarded from: X"
    # to a person rather than just the group.
    with sqlite3.connect(settings.sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        known_authors = {
            r["author_id"]: dict(r)
            for r in conn.execute(
                "SELECT author_id, display_name, channel, channel_type FROM input_authors"
            ).fetchall()
        }

    images = _iter_images(folder)
    if args.limit:
        images = images[: args.limit]
    print(f"found {len(images)} images under {folder}")

    stats = {"total": len(images), "imported": 0, "skipped_dup": 0,
             "skipped_unreadable": 0, "by_author": {}, "analyzed": 0,
             "analysis_failed": 0}

    with sqlite3.connect(settings.sqlite_path) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        # Pre-fetch existing sha256s once so dedupe is O(1) per image
        # (uses extracted_features_json.image_sha256 from vision_cache plus
        # we'll also dedupe on attachment basename via a side index).
        existing_hashes: set[str] = set()
        try:
            existing_hashes = {
                row[0] for row in conn.execute(
                    "SELECT image_sha256 FROM vision_cache"
                ).fetchall()
            }
        except sqlite3.OperationalError:
            pass

        # Also dedupe against documents we already imported via this script:
        # we store sha256 in extracted_features_json on archive imports.
        try:
            for row in conn.execute(
                "SELECT json_extract(extracted_features_json, '$.image_sha256') "
                "FROM documents WHERE extracted_features_json IS NOT NULL"
            ):
                if row[0]:
                    existing_hashes.add(row[0])
        except sqlite3.OperationalError:
            pass

        for i, image_path in enumerate(images, 1):
            try:
                image_bytes = image_path.read_bytes()
            except Exception as e:
                print(f"  [{i}/{len(images)}] UNREADABLE {image_path.name}: {e}")
                stats["skipped_unreadable"] += 1
                continue

            if not image_bytes:
                stats["skipped_unreadable"] += 1
                continue

            sha = hashlib.sha256(image_bytes).hexdigest()
            if sha in existing_hashes:
                print(f"  [{i}/{len(images)}] dup-skip {image_path.name}")
                stats["skipped_dup"] += 1
                continue
            existing_hashes.add(sha)

            # OCR fast-path: extract author/channel/ticker/timeframe from
            # overlay text BEFORE doing anything destructive.
            ocr = ocr_image(image_path)

            author_ref = _resolve_author(
                ocr_channel=ocr.channel,
                ocr_channel_type=ocr.channel_type,
                ocr_author=ocr.author,
                default_author=default_author,
                known_authors=known_authors,
            )
            author_id = upsert_author(author_ref) if not args.dry_run else slugify_author(author_ref)
            stats["by_author"][author_id] = stats["by_author"].get(author_id, 0) + 1

            if args.dry_run:
                print(f"  [{i}/{len(images)}] {image_path.name} → "
                      f"author={author_id} ticker={ocr.ticker} tf={ocr.timeframe}")
                stats["imported"] += 1
                continue

            rel_path, _ = _save_attachment(image_bytes, image_path.name, base_dir)

            # Build the documents row (mirror processor.ingest shape).
            now = datetime.now(UTC).isoformat()
            document_id = uuid.uuid4().hex
            ticker = ocr.ticker or ""
            tf = ocr.timeframe
            tags = sorted({"manual", "chart", "vision"} | (
                {"crypto"} if ticker and ("USD" in ticker or "/" in ticker) else set()
            ))
            user_meta = {
                "user": {
                    "ticker": ticker or None,
                    "side": None,
                    "conviction": None,
                    "timeframe": tf,
                    "note": None,
                },
                "resolved": {
                    "ticker": ticker or None,
                    "side": None,
                    "conviction": None,
                    "timeframe": tf,
                    "note": None,
                },
                "channel": author_ref.channel,
                "channel_type": author_ref.channel_type,
            }
            tags_payload = {
                "tags": tags,
                "agents": sorted(route_to_agents(set(tags))),
                "pending_vision": True,
                "tickers": [ticker] if ticker else [],
                "source": "bulk_import_screenshots",
                "bulk_imported_from": str(image_path),
            }

            title_bits = [ticker, author_ref.display_name]
            title = " · ".join(b for b in title_bits if b) or image_path.name

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
                    title,
                    None,
                    ocr.published_at or now,
                    author_ref.display_name,
                    "manual_chart",
                    "",   # raw_text: empty for image-only drops
                    "",
                    json.dumps(tags_payload),
                    now,
                    author_id,
                    json.dumps(user_meta),
                    rel_path,
                    json.dumps({"image_sha256": sha}),  # placeholder so dedupe works
                    json.dumps([rel_path]),
                ),
            )
            conn.commit()
            stats["imported"] += 1
            print(f"  [{i}/{len(images)}] imported {image_path.name} → "
                  f"author={author_id}{(' ticker=' + ticker) if ticker else ''}")

            # Inline drain — Claude vision per image. Slow but immediate.
            if args.analyze:
                try:
                    from macro_positioning.manual.vision_drainer import drain
                    s = drain(document_id=document_id)
                    if s.processed:
                        stats["analyzed"] += 1
                    else:
                        stats["analysis_failed"] += 1
                except Exception as e:
                    print(f"      analyze error: {e}")
                    stats["analysis_failed"] += 1

    print()
    print(f"=== summary{' (dry-run)' if args.dry_run else ''} ===")
    print(f"  total              {stats['total']}")
    print(f"  imported           {stats['imported']}")
    print(f"  skipped (dup)      {stats['skipped_dup']}")
    print(f"  skipped (unread)   {stats['skipped_unreadable']}")
    if args.analyze:
        print(f"  analyzed inline    {stats['analyzed']}")
        print(f"  analyze failed     {stats['analysis_failed']}")
    print("  by author:")
    for aid, n in sorted(stats["by_author"].items(), key=lambda kv: -kv[1]):
        print(f"    {aid:30s} {n}")
    if not args.analyze and stats["imported"]:
        print()
        print("  Next: drain vision in the background ↓")
        print('    curl -X POST "http://127.0.0.1:8001/api/manual/vision/drain?limit=200"')
        print("  Or just hit the `analyze pending` button in /04 manual input.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

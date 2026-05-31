"""Import sequentially-captured Telegram chat screenshots, grouped into drops.

Workflow this script is built for:
  1. You screenshot the CHART(s) shared in a Telegram message.
  2. Then you screenshot the MESSAGE itself (the bubble with the
     "Forwarded from: X" header, the caption text, and a smaller copy of
     the chart embedded).
  3. Sometimes one message carries TWO charts → you screenshot both
     charts first, then the message. So the run is: chart, chart, msg,
     chart, msg, chart, chart, msg, ...

This script walks the folder in filename order (macOS Screenshot YYYY-MM-DD
at HH.MM.SS naming sorts chronologically), runs OCR on each image to
classify it as CHART vs MESSAGE, then groups every run of charts with the
NEXT message into a single `documents` row whose:

  - attachment_paths_json carries [chart_1, chart_2, ..., message] — the
    message screenshot last so the vision drainer sees the rich caption +
    chart context after the pure chart views.
  - author/channel are pulled from the message screenshot's TG header
    (matched against the seeded picklist when possible; otherwise a new
    input_authors row is created on the fly).
  - raw_text is OCR'd from the message screenshot (the user's caption +
    "Forwarded from: ..." header).
  - tags_json.pending_vision = true (the drainer will run Claude on all
    attachments and merge into one TradeRecord per group).

Idempotent: SHA256 of every chart screenshot is recorded; re-running the
script on the same folder is a no-op for already-imported groups.

Usage:
    # Dry-run shows the grouping before any DB writes:
    uv run python scripts/import_grouped_telegram_screenshots.py \\
        --dir manual_inputs/screenshots --dry-run

    # Real run, queue for vision drainer:
    uv run python scripts/import_grouped_telegram_screenshots.py \\
        --dir manual_inputs/screenshots

    # Real run + analyze each group inline (slow, ~20s × charts × groups):
    uv run python scripts/import_grouped_telegram_screenshots.py \\
        --dir manual_inputs/screenshots --analyze
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import uuid
from dataclasses import dataclass, field
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


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif", ".heic"}


@dataclass
class Classified:
    """One screenshot with its OCR result + computed type."""
    path: Path
    kind: str  # "chart" | "message" | "unknown"
    ocr_channel: Optional[str] = None
    ocr_channel_type: Optional[str] = None
    ocr_author: Optional[str] = None
    ocr_ticker: Optional[str] = None
    ocr_timeframe: Optional[str] = None
    # ISO 8601 timestamp extracted from the TradingView header overlay
    # ("Big_Nuts created with TradingView.com, May 07, 2026 03:01 UTC-7").
    # This is the *chart capture date* — critical for time-weighted scoring
    # so a 6-month-old setup carries less signal than yesterday's.
    ocr_published_at: Optional[str] = None
    ocr_text: str = ""


@dataclass
class Group:
    """One logical drop = N chart screenshots + one trailing message."""
    charts: list[Classified] = field(default_factory=list)
    message: Optional[Classified] = None
    sequence: int = 0


def _normalize_channel(raw: Optional[str]) -> Optional[str]:
    """Strip emoji/non-alphanumeric noise tesseract picks up as '##' or '@@'.

    The OCR'd 'Forwarded from: <emoji> Channel Name' often comes back as
    '## Channel Name' or '@@ Channel Name Feb.' — clean it so the channel
    matcher has a clean string to compare against seeded values.
    """
    if not raw:
        return None
    s = raw.strip()
    # Strip leading noise (##, @@, » etc.)
    s = re.sub(r"^[^A-Za-z0-9]+", "", s)
    # Trim trailing tesseract artifacts like " Feb." (truncation noise)
    s = re.sub(r"\s+(Feb|Jan|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?$", "", s)
    s = s.strip()
    return s or None


def _classify(path: Path) -> Classified:
    """Run OCR + decide if this is a chart or a message screenshot."""
    sug = ocr_image(path)
    kind = "unknown"
    if sug.detected_format == "telegram_forward":
        kind = "message"
    elif sug.detected_format == "tradingview_chart":
        kind = "chart"
    else:
        # Fallback: if substantial prose lines present, treat as message;
        # otherwise assume chart (safer default since charts dominate volume).
        text = sug.raw_text or ""
        prose_lines = sum(
            1 for line in text.splitlines()
            if len(line.split()) >= 5
        )
        kind = "message" if prose_lines >= 3 else "chart"
    return Classified(
        path=path,
        kind=kind,
        ocr_channel=_normalize_channel(sug.channel),
        ocr_channel_type=sug.channel_type,
        ocr_author=sug.author,
        ocr_ticker=sug.ticker,
        ocr_timeframe=sug.timeframe,
        ocr_published_at=sug.published_at,
        ocr_text=sug.raw_text or "",
    )


def _group_screenshots(items: list[Classified]) -> list[Group]:
    """Walk in order, batch CHART runs with the next MESSAGE.

    A run of charts terminated by a message becomes one drop. Trailing
    charts with no closing message become their own drop (the user may
    have screenshotted a chart but never the message — still worth
    capturing).
    """
    groups: list[Group] = []
    cur_charts: list[Classified] = []
    seq = 0
    for it in items:
        if it.kind == "message":
            seq += 1
            groups.append(Group(charts=cur_charts, message=it, sequence=seq))
            cur_charts = []
        else:
            cur_charts.append(it)
    if cur_charts:
        seq += 1
        groups.append(Group(charts=cur_charts, message=None, sequence=seq))
    return groups


def _resolve_author(
    *,
    msg: Optional[Classified],
    default_author: AuthorRef,
    known_authors: dict[str, dict],
) -> AuthorRef:
    """Map a group to an author/channel using the message screenshot's OCR
    (the chart screenshots themselves have no TG attribution).

    Match order:
      1. OCR'd channel from message → seeded author whose channel matches.
      2. OCR'd channel only (no seed hit) → new author entry with the
         channel name as both display + channel.
      3. No message OR no channel detected → default_author.
    """
    if msg is None:
        return default_author

    channel = msg.ocr_channel
    if channel:
        # Exact (case-insensitive) match against seeded channels
        for a in known_authors.values():
            if (a.get("channel") or "").strip().lower() == channel.strip().lower():
                return AuthorRef(
                    display_name=a["display_name"],
                    channel=a.get("channel"),
                    channel_type=a.get("channel_type") or msg.ocr_channel_type or "telegram",
                )
        # No seed match — register this group's channel as a new author.
        return AuthorRef(
            display_name=channel,
            channel=channel,
            channel_type=msg.ocr_channel_type or "telegram",
        )

    if msg.ocr_author:
        return AuthorRef(
            display_name=msg.ocr_author,
            channel=default_author.channel,
            channel_type=default_author.channel_type,
        )

    return default_author


def _save_attachment(image_bytes: bytes, original_name: str, base_dir: Path) -> tuple[str, Path]:
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
    ap.add_argument("--dir", required=True, type=Path)
    ap.add_argument("--default-author", default="Me",
                    help='Fallback author when OCR cant detect from a message screenshot.')
    ap.add_argument("--default-channel", default="self")
    ap.add_argument("--default-channel-type", default="self")
    ap.add_argument("--analyze", action="store_true",
                    help="Drain Claude vision inline per group after import.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show the grouping + attribution, no DB writes.")
    ap.add_argument("--limit", type=int, default=0,
                    help="Cap number of source images processed (0 = all).")
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

    # Snapshot seeded authors so OCR'd channels can map to a known person.
    with sqlite3.connect(settings.sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        known_authors = {
            r["author_id"]: dict(r)
            for r in conn.execute(
                "SELECT author_id, display_name, channel, channel_type FROM input_authors"
            ).fetchall()
        }

    # 1. Sort + classify every image.
    files = sorted(
        p for p in folder.rglob("*")
        if p.is_file() and p.suffix.lower() in _IMAGE_EXTS
    )
    if args.limit:
        files = files[: args.limit]
    print(f"found {len(files)} screenshots in {folder}\n")
    print("[classify]")
    classified: list[Classified] = []
    for f in files:
        c = _classify(f)
        classified.append(c)
        print(f"  {c.kind.upper():7s} {f.name[:60]}"
              + (f"  channel={c.ocr_channel}" if c.ocr_channel else "")
              + (f"  ticker={c.ocr_ticker}" if c.ocr_ticker else ""))

    # 2. Group runs of charts with following message.
    groups = _group_screenshots(classified)
    print(f"\n[group]  → {len(groups)} drops from {len(files)} screenshots")
    for g in groups:
        ch_count = len(g.charts)
        msg = "—" if g.message is None else g.message.path.name
        print(f"  #{g.sequence:>2}  {ch_count} chart(s) + msg={msg}")

    # 2b. SMART DEFAULT: if a dominant channel emerges from the OCR (>=60%
    # of groups attribute to one source), promote it to the default for
    # the groups where OCR failed. Avoids the failure mode where a few
    # garbled message screenshots get dumped on `--default-author Me`
    # when they clearly came from the same chat as everything else.
    channel_counts: dict[str, int] = {}
    for g in groups:
        ch = _normalize_channel(g.message.ocr_channel if g.message else None)
        if ch:
            channel_counts[ch] = channel_counts.get(ch, 0) + 1
    if channel_counts:
        dominant, count = max(channel_counts.items(), key=lambda kv: kv[1])
        if count >= 0.6 * len(groups):
            print(f"\n[smart-default] dominant channel '{dominant}' "
                  f"({count}/{len(groups)} groups) → overriding --default-author "
                  f"for the OCR-failed groups")
            default_author = AuthorRef(
                display_name=dominant,
                channel=dominant,
                channel_type="telegram",
            )

    if args.dry_run:
        print(f"\n=== dry-run summary ===")
        print(f"  drops:           {len(groups)}")
        return 0

    # 3. Pre-fetch existing sha256 set so we don't reimport groups.
    with sqlite3.connect(settings.sqlite_path) as conn:
        existing_hashes: set[str] = set()
        try:
            existing_hashes = {row[0] for row in conn.execute(
                "SELECT image_sha256 FROM vision_cache").fetchall()}
        except sqlite3.OperationalError:
            pass
        try:
            for row in conn.execute(
                "SELECT json_extract(extracted_features_json, '$.image_sha256') "
                "FROM documents WHERE extracted_features_json IS NOT NULL"
            ):
                if row[0]:
                    existing_hashes.add(row[0])
        except sqlite3.OperationalError:
            pass

    # 4. Per-group: save attachments, create one document.
    stats = {"imported": 0, "skipped_dup": 0, "analyzed": 0, "analysis_failed": 0,
             "by_author": {}}
    base_dir = settings.base_dir.resolve()
    with sqlite3.connect(settings.sqlite_path) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        for g in groups:
            # Skip if first chart's hash is already imported (idempotent).
            first_for_hash = g.charts[0] if g.charts else g.message
            if not first_for_hash:
                continue
            try:
                first_bytes = first_for_hash.path.read_bytes()
            except Exception as e:
                print(f"  group #{g.sequence}: unreadable first image: {e}")
                continue
            first_sha = hashlib.sha256(first_bytes).hexdigest()
            if first_sha in existing_hashes:
                print(f"  group #{g.sequence}: dup-skip (first image already imported)")
                stats["skipped_dup"] += 1
                continue
            existing_hashes.add(first_sha)

            author_ref = _resolve_author(
                msg=g.message,
                default_author=default_author,
                known_authors=known_authors,
            )
            author_id = upsert_author(author_ref)
            stats["by_author"][author_id] = stats["by_author"].get(author_id, 0) + 1

            # Save all attachments — charts first, message last.
            saved: list[str] = []
            for item in g.charts + ([g.message] if g.message else []):
                b = item.path.read_bytes()
                rel, _ = _save_attachment(b, item.path.name, base_dir)
                saved.append(rel)
                existing_hashes.add(hashlib.sha256(b).hexdigest())

            # Pull metadata. Prefer ticker/timeframe from the FIRST chart
            # (chart-only screenshots have cleaner TV header OCR than
            # smaller embedded chart in message screenshot).
            ticker = ""
            timeframe = None
            for c in g.charts:
                if c.ocr_ticker and not ticker:
                    ticker = c.ocr_ticker
                if c.ocr_timeframe and not timeframe:
                    timeframe = c.ocr_timeframe
                if ticker and timeframe:
                    break

            # Caption: the message screenshot's OCR text minus the
            # "Forwarded from" line (already captured as author).
            caption = ""
            # published_at: prefer the CHART's TradingView header date —
            # that's the actual analysis capture moment. Fall back to the
            # message OCR's date (rare), then today. Critical for time-
            # weighted scoring downstream.
            chart_dates = [c.ocr_published_at for c in g.charts if c.ocr_published_at]
            msg_date = g.message.ocr_published_at if g.message else None
            if chart_dates:
                published_at = chart_dates[0]
            elif msg_date:
                published_at = msg_date
            else:
                published_at = datetime.now(UTC).isoformat()
            if g.message:
                lines = [l for l in g.message.ocr_text.splitlines()
                         if l.strip() and "Forwarded from" not in l]
                caption = "\n".join(lines).strip()

            tags = sorted({"manual", "chart", "vision"} | (
                {"crypto"} if ticker and ("USD" in ticker or "/" in ticker) else set()
            ))
            tags_payload = {
                "tags": tags,
                "agents": sorted(route_to_agents(set(tags))),
                "pending_vision": True,
                "tickers": [ticker] if ticker else [],
                "source": "import_grouped_telegram_screenshots",
                "chart_count": len(g.charts),
                "has_message": g.message is not None,
            }
            user_meta = {
                "user": {
                    "ticker": ticker or None,
                    "side": None,
                    "conviction": None,
                    "timeframe": timeframe,
                    "note": (caption or "")[:280] or None,
                },
                "resolved": {
                    "ticker": ticker or None,
                    "side": None,
                    "conviction": None,
                    "timeframe": timeframe,
                    "note": (caption or "")[:280] or None,
                },
                "channel": author_ref.channel,
                "channel_type": author_ref.channel_type,
            }

            document_id = uuid.uuid4().hex
            title = " · ".join(b for b in [ticker, author_ref.display_name] if b) \
                    or f"group #{g.sequence}"
            now = datetime.now(UTC).isoformat()
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
                    published_at,
                    author_ref.display_name,
                    "manual_chart",
                    caption,
                    caption,
                    json.dumps(tags_payload),
                    now,
                    author_id,
                    json.dumps(user_meta),
                    saved[0],
                    json.dumps({"image_sha256": first_sha,
                                "chart_count": len(g.charts),
                                "has_message": g.message is not None}),
                    json.dumps(saved),
                ),
            )
            conn.commit()
            print(f"  group #{g.sequence}: imported {len(saved)} files → "
                  f"author={author_id}{(' ticker=' + ticker) if ticker else ''}")
            stats["imported"] += 1

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
    print("=== summary ===")
    print(f"  drops imported   {stats['imported']}")
    print(f"  drops skipped    {stats['skipped_dup']}")
    if args.analyze:
        print(f"  analyzed inline  {stats['analyzed']}")
        print(f"  analyze failed   {stats['analysis_failed']}")
    print("  by author:")
    for aid, n in sorted(stats["by_author"].items(), key=lambda kv: -kv[1]):
        print(f"    {aid:35s} {n}")
    if not args.analyze:
        print()
        print("  Next: drain vision (each call processes one group at a time):")
        print('    curl -X POST "http://127.0.0.1:8000/api/manual/vision/drain?limit=50"')
        print("  Or hit the `analyze pending` button in /04 manual input.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

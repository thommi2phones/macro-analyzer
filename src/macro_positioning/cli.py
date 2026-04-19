"""Command-line entrypoint for ad-hoc pipeline runs.

Usage:
    python -m macro_positioning.cli sample
    python -m macro_positioning.cli rss --feed alpha=https://example.com/feed.xml
    python -m macro_positioning.cli text --source-id local --title "My note" --file note.txt
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from macro_positioning.core.models import RawDocument
from macro_positioning.ingestion.rss_connector import ingest_feeds
from macro_positioning.ingestion.sample_sources import sample_context, sample_documents
from macro_positioning.pipelines.run_pipeline import build_pipeline


def _parse_feed_arg(raw: str) -> tuple[str, str]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError(
            f"--feed expects source_id=url form, got {raw!r}"
        )
    source_id, url = raw.split("=", 1)
    return source_id.strip(), url.strip()


def cmd_sample(_: argparse.Namespace) -> int:
    pipeline = build_pipeline()
    result = pipeline.run(sample_documents(), context=sample_context())
    print(result.model_dump_json(indent=2))
    return 0


def cmd_rss(args: argparse.Namespace) -> int:
    feeds: list[tuple[str, str]] = args.feed or []
    if not feeds:
        print("No feeds provided. Use --feed source_id=url", file=sys.stderr)
        return 2
    documents = ingest_feeds(feeds, max_items_per_feed=args.max_items)
    if not documents:
        print("Fetched 0 documents from feeds.", file=sys.stderr)
        return 1
    pipeline = build_pipeline()
    result = pipeline.run(documents)
    print(result.model_dump_json(indent=2))
    return 0


def cmd_text(args: argparse.Namespace) -> int:
    text_body = Path(args.file).read_text() if args.file else args.text
    if not text_body:
        print("Provide --file or --text", file=sys.stderr)
        return 2
    doc = RawDocument(
        source_id=args.source_id,
        title=args.title,
        url=args.url,
        published_at=datetime.now(timezone.utc),
        author=args.author,
        content_type="note",
        raw_text=text_body,
        tags=args.tag or [],
    )
    pipeline = build_pipeline()
    result = pipeline.run([doc])
    print(result.model_dump_json(indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="macro-positioning",
        description="Macro Positioning Analyzer CLI",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="enable INFO-level logging"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_sample = sub.add_parser("sample", help="run the pipeline against the bundled sample data")
    p_sample.set_defaults(func=cmd_sample)

    p_rss = sub.add_parser("rss", help="ingest RSS feeds and run the pipeline")
    p_rss.add_argument(
        "--feed",
        action="append",
        type=_parse_feed_arg,
        help="repeatable: source_id=feed_url",
    )
    p_rss.add_argument("--max-items", type=int, default=15)
    p_rss.set_defaults(func=cmd_rss)

    p_text = sub.add_parser("text", help="ingest a single text blob or file")
    p_text.add_argument("--source-id", required=True)
    p_text.add_argument("--title", required=True)
    p_text.add_argument("--file", help="path to a text file")
    p_text.add_argument("--text", help="inline raw text")
    p_text.add_argument("--url", default=None)
    p_text.add_argument("--author", default=None)
    p_text.add_argument("--tag", action="append", default=None)
    p_text.set_defaults(func=cmd_text)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

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
from macro_positioning.ingestion.source_lifecycle import (
    add_source,
    archive_source,
    count_by_priority,
    promote_source,
    retag_source,
    summarize_sources,
)
from macro_positioning.pipelines.run_pipeline import build_pipeline
from macro_positioning.scoring.runner import run_scoring_pass


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


def cmd_sources_list(args: argparse.Namespace) -> int:
    rows = summarize_sources(include_archived=args.all)
    if not rows:
        print("(no sources)")
        return 0
    # Header + rows; minimal, monospaced, columnar output
    print(f"{'PRIORITY':<10}  {'TYPE':<14}  {'TRUST':>6}  {'SOURCE_ID':<28}  TAGS")
    print("-" * 100)
    for r in rows:
        tags_str = ",".join(r.routing_tags[:6]) + ("…" if len(r.routing_tags) > 6 else "")
        print(
            f"{r.priority:<10}  {r.source_type:<14}  {r.trust_weight:>6.2f}  {r.source_id:<28}  {tags_str}"
        )
    print()
    counts = count_by_priority()
    summary = "  ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    print(f"summary: total={sum(counts.values())}  {summary}")
    return 0


def cmd_sources_add(args: argparse.Namespace) -> int:
    try:
        rec = add_source(
            args.source_id,
            name=args.name,
            source_type=args.type,
            author=args.author or "",
            priority=args.priority,
            trust_weight=args.trust,
            market_focus=args.focus or [],
            routing_tags=args.tag or [],
            fetch_cadence=args.cadence,
            freshness_sla_hours=args.sla,
            channels=[{"channel_type": "url", "label": "primary", "url": args.url}] if args.url else [],
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"Onboarded {rec.source_id} (priority={rec.priority}, trust={rec.trust_weight}, tags={','.join(rec.routing_tags) or '-'})")
    return 0


def cmd_sources_archive(args: argparse.Namespace) -> int:
    try:
        rec = archive_source(args.source_id)
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"Archived {rec.source_id} on {rec.archived_at}")
    return 0


def cmd_sources_promote(args: argparse.Namespace) -> int:
    try:
        rec = promote_source(args.source_id, args.to)
    except (KeyError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"Promoted {rec.source_id} → priority={rec.priority}")
    return 0


def cmd_sources_retag(args: argparse.Namespace) -> int:
    try:
        rec = retag_source(args.source_id, add=args.add or [], remove=args.remove or [])
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"{rec.source_id} routing_tags: {','.join(rec.routing_tags) or '-'}")
    return 0


def cmd_score_run(args: argparse.Namespace) -> int:
    """Run a scoring pass: resolve watchlist (anchors + themes + mentions),
    score each ticker via macro_brain orchestrator, persist to trade_scores.
    """
    summary = run_scoring_pass(
        framework_regime_hint=args.regime_hint,
        persist=not args.dry_run,
        docs_window_days=args.window,
    )
    print(f"Scoring pass {summary.run_id[:8]}")
    print(f"  Regime    : {summary.framework_regime} (thesis: {summary.thesis_regime})")
    print(f"  Watchlist : {summary.watchlist_size} tickers")
    print(f"  Scored    : {summary.scored}{' (dry-run, not persisted)' if args.dry_run else f' (persisted: {summary.persisted})'}")
    if summary.mention_summary:
        print(f"  Mentions  :")
        for window, info in sorted(summary.mention_summary.items()):
            top_str = ", ".join(f"{t['ticker']}({t['docs']})" for t in info.get("top_5", []))
            print(f"    {window:>3}d : {info.get('total_docs_scanned', 0)} docs scanned, "
                  f"{info.get('tickers_above_threshold', 0)} tickers above threshold "
                  f"{f'· top: {top_str}' if top_str else ''}")
    if summary.errors:
        print(f"  Errors    : {len(summary.errors)}")
        for err in summary.errors[:5]:
            print(f"    - {err.get('ticker')}: {err.get('error')}")
    return 0 if not summary.errors else 1


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

    # ---- sources management ------------------------------------------------
    p_sources = sub.add_parser("sources", help="manage the canonical source registry (config/sources.json)")
    sources_sub = p_sources.add_subparsers(dest="sources_command", required=True)

    p_list = sources_sub.add_parser("list", help="list active sources (use --all to include archived)")
    p_list.add_argument("--all", action="store_true", help="include archived sources")
    p_list.set_defaults(func=cmd_sources_list)

    p_add = sources_sub.add_parser("add", help="onboard a new source")
    p_add.add_argument("source_id", help="snake_case unique id")
    p_add.add_argument("--name", required=True)
    p_add.add_argument("--type", required=True, help="newsletter|podcast|rss|api|gmail|manual_notes|chart")
    p_add.add_argument("--author", default=None)
    p_add.add_argument("--priority", default="trial", choices=["core", "secondary", "trial"])
    p_add.add_argument("--trust", type=float, default=0.5)
    p_add.add_argument("--focus", action="append", default=None, help="repeatable: market_focus tag")
    p_add.add_argument("--tag", action="append", default=None, help="repeatable: routing_tag")
    p_add.add_argument("--cadence", default="manual", help="ISO-8601 duration or 'manual' or 'realtime'")
    p_add.add_argument("--sla", type=int, default=None, help="freshness_sla_hours")
    p_add.add_argument("--url", default=None, help="primary channel URL")
    p_add.set_defaults(func=cmd_sources_add)

    p_arch = sources_sub.add_parser("archive", help="archive a source (soft delete)")
    p_arch.add_argument("source_id")
    p_arch.set_defaults(func=cmd_sources_archive)

    p_promote = sources_sub.add_parser("promote", help="change a source's priority")
    p_promote.add_argument("source_id")
    p_promote.add_argument("--to", required=True, choices=["core", "secondary", "trial", "archived"])
    p_promote.set_defaults(func=cmd_sources_promote)

    p_retag = sources_sub.add_parser("retag", help="adjust a source's routing_tags")
    p_retag.add_argument("source_id")
    p_retag.add_argument("--add", action="append", default=None, help="repeatable: tag to add")
    p_retag.add_argument("--remove", action="append", default=None, help="repeatable: tag to remove")
    p_retag.set_defaults(func=cmd_sources_retag)

    # ---- scoring ------------------------------------------------------------
    p_score = sub.add_parser("score", help="run brain scoring against the active watchlist")
    score_sub = p_score.add_subparsers(dest="score_command", required=True)

    p_run = score_sub.add_parser("run", help="resolve watchlist + score each ticker + persist")
    p_run.add_argument("--regime-hint", default=None, help="override thesis regime (e.g. 'commodity_expansion')")
    p_run.add_argument("--dry-run", action="store_true", help="compute but don't persist to trade_scores")
    p_run.add_argument("--window", type=int, default=90, help="document lookback days for mention extraction")
    p_run.set_defaults(func=cmd_score_run)

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

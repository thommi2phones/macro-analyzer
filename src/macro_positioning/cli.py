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
from macro_positioning.core.settings import settings
from macro_positioning.db.schema import initialize_database
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
from macro_positioning.learning import (
    attribution as learning_attribution,
    author_attribution as learning_author_attribution,
    backfill_model_versions as learning_backfill_model_versions,
    backfill_quality_scores as learning_backfill_quality_scores,
    conviction_calibration as learning_conviction_calibration,
    mention_precision as learning_mention_precision,
    quality_summary as learning_quality_summary,
    score_outcome_correlation as learning_correlation,
    signal_attribution as learning_signal_attribution,
    signal_history as learning_signal_history,
    version_stats as learning_version_stats,
)
from macro_positioning.pipelines.run_pipeline import build_pipeline
from macro_positioning.prices.fetcher import fetch_and_persist as fetch_prices_persist
from macro_positioning.scoring.runner import run_scoring_pass
from macro_positioning.scoring.watchlist_resolver import resolve_watchlist


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


def cmd_prices_fetch(args: argparse.Namespace) -> int:
    """Fetch + persist daily OHLCV bars for tickers (yfinance default)."""
    if args.ticker:
        tickers = list(args.ticker)
    elif args.watchlist:
        # Resolve current watchlist (anchors + theme tickers for current regime)
        # Mention extraction skipped here — we just need the set to fetch.
        # Use a default regime; runner re-resolves at scoring time anyway.
        resolved = resolve_watchlist(framework_regime="commodity_led_inflation")
        tickers = [e.ticker for e in resolved.entries]
    else:
        print("Provide --watchlist or --ticker T (repeatable)", file=sys.stderr)
        return 2

    result = fetch_prices_persist(tickers, days=args.days)
    print(f"Price fetch via {result.provider}")
    print(f"  Requested      : {result.tickers_requested}")
    print(f"  With data      : {result.tickers_with_data}")
    print(f"  Bars persisted : {result.bars_persisted}")
    if result.failures:
        print(f"  Failures       : {len(result.failures)}")
        for f in result.failures[:8]:
            print(f"    - {f.get('ticker'):<6}: {f.get('error')}")
    return 0 if not result.failures else 1


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


# ---------------------------------------------------------------------------
# learning — read-side analytics over agent_call_log / source_outcomes / etc.
# ---------------------------------------------------------------------------

def _learning_connect():
    import sqlite3
    initialize_database(settings.sqlite_path)
    return sqlite3.connect(settings.sqlite_path)


def cmd_learning_attribution(args: argparse.Namespace) -> int:
    import json as _json
    conn = _learning_connect()
    try:
        rows = learning_attribution(conn, window_days=args.window)
    finally:
        conn.close()
    print(_json.dumps(rows, indent=2))
    return 0


def cmd_learning_signals(args: argparse.Namespace) -> int:
    import json as _json
    conn = _learning_connect()
    try:
        horizons = tuple(args.horizons) if args.horizons else (7, 30, 90)
        rows = learning_signal_attribution(
            conn, horizons=horizons, sort_mode=args.sort_mode
        )
    finally:
        conn.close()
    print(_json.dumps(rows, indent=2))
    return 0


def cmd_learning_authors(args: argparse.Namespace) -> int:
    import json as _json
    conn = _learning_connect()
    try:
        horizons = tuple(args.horizons) if args.horizons else (7, 30, 90)
        rows = learning_author_attribution(
            conn, horizons=horizons, include_meta=args.with_meta
        )
    finally:
        conn.close()
    print(_json.dumps(rows, indent=2))
    return 0


def cmd_learning_conviction(args: argparse.Namespace) -> int:
    import json as _json
    conn = _learning_connect()
    try:
        horizons = tuple(args.horizons) if args.horizons else (7, 30, 90)
        result = learning_conviction_calibration(conn, horizons=horizons)
    finally:
        conn.close()
    print(_json.dumps(result, indent=2))
    return 0


def cmd_learning_signal_history(args: argparse.Namespace) -> int:
    import json as _json
    conn = _learning_connect()
    try:
        rows = learning_signal_history(
            conn, args.source_id, horizon=args.horizon, bucket=args.bucket
        )
    finally:
        conn.close()
    print(_json.dumps(rows, indent=2))
    return 0


def cmd_learning_correlation(args: argparse.Namespace) -> int:
    import json as _json
    conn = _learning_connect()
    try:
        result = learning_correlation(conn)
    finally:
        conn.close()
    print(_json.dumps(result, indent=2))
    return 0


def cmd_learning_version_backfill(args: argparse.Namespace) -> int:
    import json as _json
    conn = _learning_connect()
    try:
        result = learning_backfill_model_versions(conn, dry_run=args.dry_run)
    finally:
        conn.close()
    print(_json.dumps(result, indent=2))
    return 0


def cmd_learning_version_stats(args: argparse.Namespace) -> int:
    import json as _json
    conn = _learning_connect()
    try:
        result = learning_version_stats(conn)
    finally:
        conn.close()
    print(_json.dumps(result, indent=2))
    return 0


def cmd_learning_quality_backfill(args: argparse.Namespace) -> int:
    import json as _json
    conn = _learning_connect()
    try:
        result = learning_backfill_quality_scores(
            conn, since_days=args.since, dry_run=args.dry_run
        )
    finally:
        conn.close()
    print(_json.dumps(result, indent=2))
    return 0


def cmd_learning_quality_summary(args: argparse.Namespace) -> int:
    import json as _json
    conn = _learning_connect()
    try:
        result = learning_quality_summary(conn)
    finally:
        conn.close()
    print(_json.dumps(result, indent=2))
    return 0


def cmd_learning_mention_precision(args: argparse.Namespace) -> int:
    import json as _json
    conn = _learning_connect()
    try:
        result = learning_mention_precision(
            conn,
            k=args.k,
            score_threshold=args.threshold,
            horizon_days=args.horizon,
        )
    finally:
        conn.close()
    print(_json.dumps(result, indent=2))
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

    # ---- prices -------------------------------------------------------------
    p_prices = sub.add_parser("prices", help="fetch + persist daily OHLCV bars")
    prices_sub = p_prices.add_subparsers(dest="prices_command", required=True)

    p_pf = prices_sub.add_parser("fetch", help="fetch daily prices for tickers (yfinance)")
    g = p_pf.add_mutually_exclusive_group(required=False)
    g.add_argument("--watchlist", action="store_true", help="fetch every ticker in active watchlist (anchors + themes)")
    p_pf.add_argument("--ticker", action="append", default=None, help="repeatable: bare ticker (URA, BTC, DXY)")
    p_pf.add_argument("--days", type=int, default=200, help="history depth (default 200, enough for 200DMA)")
    p_pf.set_defaults(func=cmd_prices_fetch)

    # ---- scoring ------------------------------------------------------------
    p_score = sub.add_parser("score", help="run brain scoring against the active watchlist")
    score_sub = p_score.add_subparsers(dest="score_command", required=True)

    p_run = score_sub.add_parser("run", help="resolve watchlist + score each ticker + persist")
    p_run.add_argument("--regime-hint", default=None, help="override thesis regime (e.g. 'commodity_expansion')")
    p_run.add_argument("--dry-run", action="store_true", help="compute but don't persist to trade_scores")
    p_run.add_argument("--window", type=int, default=90, help="document lookback days for mention extraction")
    p_run.set_defaults(func=cmd_score_run)

    # ---- learning -----------------------------------------------------------
    p_learn = sub.add_parser("learning", help="read-side analytics over the data flywheel")
    learn_sub = p_learn.add_subparsers(dest="learning_command", required=True)

    p_attr = learn_sub.add_parser(
        "attribution",
        help="per-source closed-trade P&L (lens 1a) over a rolling window",
    )
    p_attr.add_argument("--window", type=int, default=30, help="rolling window in days (default 30)")
    p_attr.set_defaults(func=cmd_learning_attribution)

    p_sig = learn_sub.add_parser(
        "signals",
        help="per-source forward-return on every mention (lens 1b)",
    )
    p_sig.add_argument(
        "--horizon",
        dest="horizons",
        type=int,
        action="append",
        help="repeatable: forward-return horizon in days (defaults to 7,30,90)",
    )
    p_sig.add_argument(
        "--sort-mode",
        default="decay_weighted",
        choices=["decay_weighted", "raw_return"],
        help="default decay_weighted: hit_rate × log(1+n) × recency decay",
    )
    p_sig.set_defaults(func=cmd_learning_signals)

    p_auth = learn_sub.add_parser(
        "authors",
        help="per-author hit-rate + forward-return on manual drops (R1)",
    )
    p_auth.add_argument(
        "--horizon",
        dest="horizons",
        type=int,
        action="append",
        help="repeatable: forward-return horizon in days (defaults to 7,30,90)",
    )
    p_auth.add_argument(
        "--with-meta",
        action="store_true",
        help="include _meta diagnostic block (recommended on empty DB)",
    )
    p_auth.set_defaults(func=cmd_learning_authors)

    p_conv = learn_sub.add_parser(
        "conviction-calibration",
        help="bucket forward returns by user.conviction (1-5) (R2)",
    )
    p_conv.add_argument(
        "--horizon",
        dest="horizons",
        type=int,
        action="append",
        help="repeatable: forward-return horizon in days (defaults to 7,30,90)",
    )
    p_conv.set_defaults(func=cmd_learning_conviction)

    p_hist = learn_sub.add_parser(
        "signal-history",
        help="time-series of one source's signal performance (monthly buckets)",
    )
    p_hist.add_argument("--source-id", required=True)
    p_hist.add_argument("--horizon", type=int, default=30)
    p_hist.add_argument("--bucket", default="month", choices=["month"])
    p_hist.set_defaults(func=cmd_learning_signal_history)

    p_corr = learn_sub.add_parser(
        "correlation",
        help="Spearman ρ between trade scores and realized P&L",
    )
    p_corr.set_defaults(func=cmd_learning_correlation)

    p_mp = learn_sub.add_parser(
        "mention-precision",
        help="precision@k of mention-driven watchlist promotions",
    )
    p_mp.add_argument("--k", type=int, default=10)
    p_mp.add_argument("--threshold", type=int, default=70, help="adjusted_total_score that counts as 'good'")
    p_mp.add_argument("--horizon", type=int, default=30, help="horizon in days for the score-well check")
    p_mp.set_defaults(func=cmd_learning_mention_precision)

    # ---- learning > version (item 7) ---------------------------------------
    p_ver = learn_sub.add_parser(
        "version",
        help="agent_call_log.model_version helpers (item 7)",
    )
    ver_sub = p_ver.add_subparsers(dest="version_command", required=True)
    p_ver_bf = ver_sub.add_parser("backfill", help="set model_version where NULL (never overwrites)")
    p_ver_bf.add_argument("--dry-run", action="store_true")
    p_ver_bf.set_defaults(func=cmd_learning_version_backfill)
    p_ver_st = ver_sub.add_parser("stats", help="per-(agent, model_version) call counts + success rate")
    p_ver_st.set_defaults(func=cmd_learning_version_stats)

    # ---- learning > quality (item 4) ---------------------------------------
    p_qual = learn_sub.add_parser(
        "quality",
        help="agent_call_log.quality_score backfill + summary (item 4)",
    )
    qual_sub = p_qual.add_subparsers(dest="quality_command", required=True)
    p_qual_bf = qual_sub.add_parser("backfill", help="heuristic-score NULL rows (conservative)")
    p_qual_bf.add_argument("--since", type=int, default=None, help="only score rows from the last N days")
    p_qual_bf.add_argument("--dry-run", action="store_true")
    p_qual_bf.set_defaults(func=cmd_learning_quality_backfill)
    p_qual_sum = qual_sub.add_parser("summary", help="avg quality per agent + per (agent, model_version)")
    p_qual_sum.set_defaults(func=cmd_learning_quality_summary)

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

#!/usr/bin/env python3
"""
Trading Agent – CLI Entry Point

Commands
────────
  run               Start the continuous scanning agent (runs until Ctrl+C)
  scan              Run a single scan cycle and exit
  analyze-trades    Analyze trade screenshot images with Claude vision
  analyze-chats     Analyze AI chat exports (ChatGPT / Claude .txt/.json) with Claude vision
  backtest          Backtest scanner rules against historical data
  validate          Check environment variables and config before running
  report            Print paper trading performance report

Examples
────────
  python main.py run
  python main.py scan
  python main.py analyze-trades --dir ./trade_images
  python main.py analyze-chats --dir ./chat_exports
  python main.py analyze-chats --dir ./chat_exports --output ./data/trade_history.json
  python main.py backtest --ticker AAPL --timeframe 1d --bars 500
  python main.py backtest --ticker AAPL --timeframe 1d --rule rsi_oversold_buy
  python main.py backtest --ticker BTC-USD --timeframe 1h --bars 1000 --use-vectorbt
  python main.py validate
  python main.py report
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_run(args: argparse.Namespace) -> None:
    from agent.loop import TradingAgent
    TradingAgent().run()


def cmd_scan(args: argparse.Namespace) -> None:
    from agent.loop import TradingAgent
    signals = TradingAgent().scan_once()
    print(f"\nTotal signals generated: {len(signals)}")


def cmd_analyze_trades(args: argparse.Namespace) -> None:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY is not set. Add it to your .env file.")
        sys.exit(1)

    images_dir    = args.dir
    output_path   = args.output
    insights_path = output_path.replace(".json", "_insights.json")
    force         = getattr(args, "force", False)

    # ── Lazy imports so the command is fast when not used ──────────────────
    from analysis.trade_history.image_analyzer import ImageTradeAnalyzer
    from analysis.trade_history.pattern_learner import PatternLearner

    print(f"\nAnalyzing trade screenshots in: {images_dir}")
    print("Using Claude claude-opus-4-6 with adaptive thinking …\n")

    # ── Load existing records so we can skip already-processed images ──────
    existing_records: list[dict] = []
    output_file = Path(output_path)
    if output_file.exists() and not force:
        try:
            existing_records = json.loads(output_file.read_text())
            already_done = {
                Path(r["image_path"]).name
                for r in existing_records
                if r.get("image_path")
            }
            print(f"  Loaded {len(existing_records)} existing records.")
            print(f"  {len(already_done)} images already processed — skipping them.")
            print(f"  (Use --force to re-analyze everything with the updated prompt)\n")
        except Exception:
            already_done = set()
    else:
        already_done = set()
        if force:
            print("  --force: re-analyzing all images with updated prompt.\n")

    analyzer = ImageTradeAnalyzer(api_key=api_key)
    new_records = analyzer.analyze_directory(images_dir, skip_names=already_done)

    if not new_records and not existing_records:
        print("\nNo trade images found or successfully analyzed.")
        return

    # ── Merge: new records overwrite existing for the same image ───────────
    if force:
        all_records = new_records
    else:
        new_by_name = {Path(r.image_path).name: r for r in new_records if r.image_path}
        merged: list[dict] = []
        replaced = 0
        for existing in existing_records:
            name = Path(existing.get("image_path","")).name
            if name in new_by_name:
                merged.append(new_by_name.pop(name).model_dump())
                replaced += 1
            else:
                merged.append(existing)
        # append any truly new ones
        for r in new_by_name.values():
            merged.append(r.model_dump())
        all_records = merged
        print(f"\n  Replaced {replaced} existing records, added {len(new_by_name)} new ones.")

    # Save raw records
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    save_list = (
        [r.model_dump() for r in all_records]
        if hasattr(all_records[0], "model_dump")
        else all_records
    )
    Path(output_path).write_text(json.dumps(save_list, indent=2, default=str))
    print(f"\nSaved {len(save_list)} trade records → {output_path}")

    # Pattern analysis
    learner  = PatternLearner(all_records)
    insights = learner.analyze()
    learner.print_report(insights)

    Path(insights_path).write_text(json.dumps(insights, indent=2, default=str))
    print(f"Saved insights → {insights_path}")
    print(
        "\nTip: Re-run `python main.py run` to apply these insights as "
        "confidence adjustments to your live scanner."
    )


def cmd_analyze_chats(args: argparse.Namespace) -> None:
    """
    Analyze AI chat export files (ChatGPT JSON, Claude markdown, plain text)
    and extract trade records to enrich the pattern learner.

    Results are MERGED with any existing trade history so that image-derived
    records and chat-derived records are combined into one insights file.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY is not set. Add it to your .env file.")
        sys.exit(1)

    chats_dir     = args.dir
    output_path   = args.output
    insights_path = output_path.replace(".json", "_insights.json")

    # ── Lazy imports ───────────────────────────────────────────────────────
    from analysis.chat_history.chat_analyzer import ChatAnalyzer
    from analysis.trade_history.image_analyzer import TradeRecord
    from analysis.trade_history.pattern_learner import PatternLearner

    # Ensure the exports directory exists so the user knows where to drop files
    chat_dir_path = Path(chats_dir)
    chat_dir_path.mkdir(parents=True, exist_ok=True)

    if not any(chat_dir_path.iterdir()):
        print(
            f"\nNo files found in: {chats_dir}\n"
            f"Drop your chat export files there and re-run.\n\n"
            f"Supported formats:\n"
            f"  • ChatGPT  → export via Settings → Data Controls → Export Data\n"
            f"               (conversations.json inside the zip)\n"
            f"  • Claude   → copy/paste conversation to a .txt or .md file\n"
            f"  • Any      → plain .txt file with conversation content\n"
        )
        return

    print(f"\nAnalyzing chat exports in: {chats_dir}")
    print("Using Claude claude-opus-4-6 with adaptive thinking …\n")

    analyzer    = ChatAnalyzer(api_key=api_key)
    new_records = analyzer.analyze_directory(chats_dir)

    if not new_records:
        print("\nNo trade records could be extracted from the chat files.")
        return

    # ── Merge with existing trade history ──────────────────────────────────
    output_file = Path(output_path)
    existing_records: list[TradeRecord] = []

    if output_file.exists():
        try:
            raw = json.loads(output_file.read_text(encoding="utf-8"))
            existing_records = [TradeRecord(**r) for r in raw]
            print(f"\nLoaded {len(existing_records)} existing records from {output_path}")
        except Exception as exc:
            print(f"Warning: could not load existing records ({exc}); starting fresh.")

    combined = existing_records + new_records

    # Deduplicate across the combined set (ticker + entry_price + direction)
    seen: set = set()
    deduped: list[TradeRecord] = []
    for r in combined:
        key = (r.ticker, r.entry_price, r.direction)
        if key not in seen:
            seen.add(key)
            deduped.append(r)

    added = len(deduped) - len(existing_records)

    # Save merged records
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps([r.model_dump() for r in deduped], indent=2, default=str),
        encoding="utf-8",
    )
    print(
        f"\nSaved {len(deduped)} total trade records → {output_path}\n"
        f"  (+{added} new from chats, {len(existing_records)} pre-existing)"
    )

    # ── Pattern analysis on full combined dataset ──────────────────────────
    learner  = PatternLearner(deduped)
    insights = learner.analyze()
    learner.print_report(insights)

    Path(insights_path).write_text(
        json.dumps(insights, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"Saved insights → {insights_path}")
    print(
        "\nTip: Re-run `python main.py run` to apply these insights as "
        "confidence adjustments to your live scanner."
    )


def cmd_backtest(args: argparse.Namespace) -> None:
    """
    Fetch historical OHLCV data for a ticker and backtest all (or one) scanner
    rules against it, reporting win rate, profit factor, Sharpe, and drawdown.
    """
    import yaml

    # ── Load config for provider credentials ───────────────────────────────
    with open("config/settings.yaml") as f:
        cfg = yaml.safe_load(f)

    provider_name = cfg["data"].get("provider", "yfinance")

    # ── Data provider ──────────────────────────────────────────────────────
    df = None
    if provider_name == "alpaca":
        api_key    = os.getenv("ALPACA_API_KEY", "")
        secret_key = os.getenv("ALPACA_SECRET_KEY", "")
        if api_key and secret_key:
            try:
                from data.providers.alpaca_provider import AlpacaProvider
                provider = AlpacaProvider(api_key, secret_key)
                df = provider.get_ohlcv(args.ticker, args.timeframe, bars=args.bars)
                print(f"Fetched {len(df)} bars via Alpaca")
            except Exception as exc:
                print(f"Alpaca fetch failed ({exc}), falling back to yfinance …")

    if df is None or df.empty:
        from data.providers.yfinance_provider import YFinanceProvider
        provider = YFinanceProvider()
        df = provider.get_ohlcv(args.ticker, args.timeframe, bars=args.bars)
        if df is None or df.empty:
            print(f"ERROR: Could not fetch data for {args.ticker} [{args.timeframe}]")
            sys.exit(1)
        print(f"Fetched {len(df)} bars via yfinance")

    # ── Backtester ─────────────────────────────────────────────────────────
    from backtesting.engine import Backtester

    bt = Backtester(
        rules_path=args.rules,
        stop_loss_pct=args.sl,
        take_profit_pct=args.tp,
    )

    print(
        f"\nBacktesting {args.ticker} [{args.timeframe}] "
        f"| {len(df)} bars "
        f"| SL={args.sl:.0%} TP={args.tp:.0%}"
        f"{'  rule=' + args.rule if args.rule else '  (all rules)'}\n"
    )

    if args.use_vectorbt:
        reports = bt.run_with_vectorbt(
            df=df,
            ticker=args.ticker,
            timeframe=args.timeframe,
            rule_name=args.rule or None,
        )
    else:
        reports = bt.run(
            df=df,
            ticker=args.ticker,
            timeframe=args.timeframe,
            rule_name=args.rule or None,
        )

    if not reports:
        print("No signals were generated. Try a longer lookback or different timeframe.")
        return

    if args.rule:
        # Single rule — print full report
        bt.print_report(reports[0])
    else:
        # All rules — print summary table, then individual reports on request
        bt.print_summary(reports)
        if args.verbose:
            for r in reports:
                bt.print_report(r)


def cmd_validate(args: argparse.Namespace) -> None:
    """
    Check that all required environment variables and config paths are present
    before attempting to start the agent.
    """
    import yaml

    ok    = True
    warns = []

    def check(name: str, label: str, required: bool = True) -> str | None:
        nonlocal ok
        val = os.getenv(name)
        status = "✅" if val else ("❌" if required else "⚠️ ")
        note   = "" if val else (" — REQUIRED" if required else " — optional")
        print(f"  {status}  {name:<30} {label}{note}")
        if required and not val:
            ok = False
        return val

    print("\n── Environment Variables ─────────────────────────────────────────")
    check("ANTHROPIC_API_KEY",    "Claude API (vision + chat analysis)", required=True)
    check("ALPACA_API_KEY",       "Alpaca market data + trading",        required=False)
    check("ALPACA_SECRET_KEY",    "Alpaca secret",                       required=False)
    check("DISCORD_WEBHOOK_URL",  "Discord alerts",                      required=False)
    check("SMTP_HOST",             "SMTP host for email alerts",          required=False)
    check("EMAIL_SENDER",          "SMTP sender address",                required=False)
    check("EMAIL_PASSWORD",        "SMTP password",                      required=False)
    check("EMAIL_RECIPIENT",       "Alert recipient address",            required=False)

    print("\n── Config Files ──────────────────────────────────────────────────")
    for cfg in ["config/settings.yaml", "config/rules.yaml"]:
        exists = Path(cfg).exists()
        print(f"  {'✅' if exists else '❌'}  {cfg}")
        if not exists:
            ok = False

    if Path("config/settings.yaml").exists():
        with open("config/settings.yaml") as f:
            cfg = yaml.safe_load(f)

        print("\n── Settings Summary ──────────────────────────────────────────────")
        provider  = cfg.get("data", {}).get("provider", "yfinance")
        exec_mode = cfg.get("execution", {}).get("mode", "paper")
        watchlist = cfg.get("watchlists", {})
        profiles  = list(cfg.get("scan_profiles", {}).keys())
        n_tickers = sum(len(v) for v in watchlist.values() if isinstance(v, list))
        print(f"  Data provider : {provider}")
        print(f"  Execution mode: {exec_mode}")
        print(f"  Watchlist     : {n_tickers} tickers")
        print(f"  Scan profiles : {', '.join(profiles) or 'none'}")

        if provider == "alpaca" and not os.getenv("ALPACA_API_KEY"):
            warns.append(
                "settings.yaml uses data.provider=alpaca but ALPACA_API_KEY is not set. "
                "The agent will fall back to yfinance."
            )

    print()
    if warns:
        print("── Warnings ──────────────────────────────────────────────────────")
        for w in warns:
            print(f"  ⚠️   {w}")
        print()

    if ok:
        print("✅  All required settings are present. You're good to go!\n")
    else:
        print("❌  Some required settings are missing. Fix them before running.\n")
        sys.exit(1)


def cmd_poll_render(args: argparse.Namespace) -> None:
    """One-shot poll of the Render webhook service for TradingView events."""
    from data.providers.render_poller import RenderPoller
    from signals.inbox_processor import InboxProcessor
    import yaml

    with open("config/settings.yaml") as f:
        cfg = yaml.safe_load(f)

    render_cfg = cfg.get("render_webhook", {})
    if not render_cfg.get("enabled", False):
        print("❌ render_webhook is not enabled in config/settings.yaml")
        sys.exit(1)

    url = render_cfg.get("url", "https://trading-agent-v1-codex.onrender.com")

    poller = RenderPoller(
        render_url=url,
        inbox_dir=render_cfg.get("inbox_dir", "signals/inbox"),
        state_file=render_cfg.get("state_file", "data/render_poll_state.json"),
    )

    # Health check
    print(f"\n── Render Webhook Poller ─────────────────────────────────────────")
    print(f"  URL: {url}")

    if not poller.health_check():
        print("  ❌ Render service is not responding")
        sys.exit(1)
    print("  ✅ Render service healthy")

    # Poll for events
    new_packets = poller.poll()
    print(f"  New events: {len(new_packets)}")

    for p in new_packets:
        print(
            f"    📡 {p.get('symbol', '?')} | "
            f"{p.get('bias', '?')} | "
            f"confluence={p.get('confluence', '?')} | "
            f"pattern={p.get('pattern', {}).get('manual_type', '?')} | "
            f"score={p.get('score', 0)}"
        )

    # Process inbox if requested
    if args.process:
        routing = render_cfg.get("signal_routing", {})
        processor = InboxProcessor(
            inbox_dir=render_cfg.get("inbox_dir", "signals/inbox"),
            signal_routing=routing,
        )
        signals = processor.process()
        print(f"\n  Processed {len(signals)} inbox events:")
        for sig in signals:
            mtf = sig.to_mtf_signal()
            print(f"    → {mtf}")
            print(f"      action={sig.action} (confluence={sig.confluence})")

    # Status
    status = poller.status()
    print(f"\n  Total events seen: {status['events_seen']}")
    print(f"  Last poll: {status['last_poll']}")
    print()


def cmd_report(args: argparse.Namespace) -> None:
    from execution.paper_trading import PaperTrader
    PaperTrader.load().print_report()


# ── CLI wiring ────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trading_agent",
        description="Personal trading agent: chart scanner + Claude vision trade analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # run
    sub.add_parser("run", help="Start the continuous scanning agent")

    # scan
    sub.add_parser("scan", help="Run one scan cycle and print results")

    # analyze-trades
    at = sub.add_parser(
        "analyze-trades",
        help="Analyze trade screenshots with Claude vision to build your personal pattern profile",
    )
    at.add_argument(
        "--dir",
        default="./trade_images",
        metavar="DIR",
        help="Folder containing trade screenshots (PNG/JPG/WEBP). Default: ./trade_images",
    )
    at.add_argument(
        "--output",
        default="./data/trade_history.json",
        metavar="FILE",
        help="Output JSON file for extracted trade records. Default: ./data/trade_history.json",
    )
    at.add_argument(
        "--force",
        action="store_true",
        help="Re-analyze ALL images even if already in trade_history.json. "
             "Use this after updating the extraction prompt.",
    )

    # analyze-chats
    ac = sub.add_parser(
        "analyze-chats",
        help=(
            "Analyze AI chat exports (ChatGPT JSON, Claude/plain text) with Claude vision "
            "and merge extracted trades into your pattern profile"
        ),
    )
    ac.add_argument(
        "--dir",
        default="./chat_exports",
        metavar="DIR",
        help=(
            "Folder containing chat export files (.txt, .md, .json). "
            "Default: ./chat_exports"
        ),
    )
    ac.add_argument(
        "--output",
        default="./data/trade_history.json",
        metavar="FILE",
        help=(
            "JSON file to merge extracted records into (same file as analyze-trades). "
            "Default: ./data/trade_history.json"
        ),
    )

    # backtest
    bk = sub.add_parser(
        "backtest",
        help="Backtest scanner rules against historical OHLCV data",
    )
    bk.add_argument(
        "--ticker",
        required=True,
        metavar="SYMBOL",
        help="Ticker to backtest (e.g. AAPL, BTC-USD, ES=F)",
    )
    bk.add_argument(
        "--timeframe",
        default="1d",
        metavar="TF",
        help="Timeframe to use: 1m 5m 15m 1h 4h 12h 1d 3d 1wk 1mo. Default: 1d",
    )
    bk.add_argument(
        "--bars",
        type=int,
        default=500,
        metavar="N",
        help="Number of historical bars to fetch. Default: 500",
    )
    bk.add_argument(
        "--rule",
        default="",
        metavar="RULE_NAME",
        help="Name of a single rule to test. Omit to test all rules.",
    )
    bk.add_argument(
        "--sl",
        type=float,
        default=0.02,
        metavar="PCT",
        help="Stop loss fraction (e.g. 0.02 = 2%%). Default: 0.02",
    )
    bk.add_argument(
        "--tp",
        type=float,
        default=0.04,
        metavar="PCT",
        help="Take profit fraction (e.g. 0.04 = 4%%). Default: 0.04",
    )
    bk.add_argument(
        "--rules",
        default="config/rules.yaml",
        metavar="FILE",
        help="Path to rules YAML. Default: config/rules.yaml",
    )
    bk.add_argument(
        "--use-vectorbt",
        action="store_true",
        help="Use vectorbt for richer portfolio statistics (requires: pip install vectorbt)",
    )
    bk.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print full per-rule reports in addition to the summary table",
    )

    # poll-render
    pr = sub.add_parser(
        "poll-render",
        help="Poll the Render webhook service for TradingView events",
    )
    pr.add_argument(
        "--process",
        action="store_true",
        help="Also process inbox events into signals (convert + route)",
    )

    # validate
    sub.add_parser(
        "validate",
        help="Check environment variables and config before running the agent",
    )

    # report
    sub.add_parser("report", help="Print paper trading performance report")

    return parser


def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    dispatch = {
        "run":             cmd_run,
        "scan":            cmd_scan,
        "analyze-trades":  cmd_analyze_trades,
        "analyze-chats":   cmd_analyze_chats,
        "backtest":        cmd_backtest,
        "poll-render":     cmd_poll_render,
        "validate":        cmd_validate,
        "report":          cmd_report,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()

"""
Main trading agent loop.

Orchestrates:
  - Data fetching (Alpaca historical + optional real-time WebSocket stream)
  - Multi-timeframe scanning with majority-vote confluence
  - Signal generation with historical confidence adjustments
  - Discord / email alerting
  - Paper or live order execution via Alpaca
"""

import logging
import logging.handlers
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml
from apscheduler.schedulers.blocking import BlockingScheduler

from agent.health import start_health_server, update_status, record_scan, record_error
from alerts import discord as discord_alert
from alerts import email_alert
from analysis.mtf_scanner import MTFScanner, MTFSignal
from analysis.scanner import Scanner
from data.providers.alpaca_provider import AlpacaProvider
from data.providers.render_poller import RenderPoller
from data.providers.yfinance_provider import YFinanceProvider
from execution.paper_trading import PaperTrader
from signals.generator import SignalGenerator
from signals.inbox_processor import InboxProcessor

logger = logging.getLogger(__name__)


def _load_config(path: str = "config/settings.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


class TradingAgent:

    def __init__(
        self,
        config_path: str = "config/settings.yaml",
        rules_path:  str = "config/rules.yaml",
    ):
        self.cfg = _load_config(config_path)
        self._setup_logging()

        # ── Data provider ─────────────────────────────────────────────────────
        provider_name = self.cfg["data"].get("provider", "yfinance")
        if provider_name == "alpaca":
            api_key    = os.getenv("ALPACA_API_KEY", "")
            secret_key = os.getenv("ALPACA_SECRET_KEY", "")
            if not api_key or not secret_key:
                logger.warning(
                    "ALPACA_API_KEY/SECRET not set — falling back to yfinance"
                )
                self._provider = YFinanceProvider()
            else:
                self._provider = AlpacaProvider(api_key, secret_key)
                logger.info("Using Alpaca data provider")
        else:
            self._provider = YFinanceProvider()
            logger.info("Using yfinance data provider")

        # ── Scanners ──────────────────────────────────────────────────────────
        single_tf_scanner = Scanner(rules_path)
        scan_profiles      = self.cfg.get("scan_profiles", {})
        self._mtf_scanner  = MTFScanner(single_tf_scanner, scan_profiles)

        # ── Signal generator (applies historical confidence boosts) ───────────
        self._signal_gen = SignalGenerator(
            scanner=single_tf_scanner,
            insights_path=self.cfg["trade_history"]["insights_file"],
            min_confidence=self.cfg["scanner"]["min_confidence"],
        )

        # ── Execution ─────────────────────────────────────────────────────────
        self._paper_trader: Optional[PaperTrader] = None
        self._alpaca_broker = None

        exec_mode = self.cfg["execution"]["mode"]
        try:
            from execution.alpaca_broker import AlpacaBroker
            is_paper = exec_mode == "paper"
            self._alpaca_broker = AlpacaBroker(paper=is_paper)
            logger.info("AlpacaBroker ready (%s)", exec_mode.upper())
        except Exception as exc:
            logger.warning(
                "AlpacaBroker unavailable: %s — using internal PaperTrader", exc
            )
            self._paper_trader = PaperTrader(
                balance=self.cfg["execution"]["paper_balance"],
                max_position_pct=self.cfg["execution"]["max_position_pct"],
                stop_loss_pct=self.cfg["execution"]["stop_loss_pct"],
                take_profit_pct=self.cfg["execution"]["take_profit_pct"],
            )

        # ── Render webhook poller + inbox processor ───────────────────────────
        render_cfg = self.cfg.get("render_webhook", {})
        self._render_enabled = render_cfg.get("enabled", False)
        self._render_poller: Optional[RenderPoller] = None
        self._inbox_processor: Optional[InboxProcessor] = None

        if self._render_enabled:
            self._render_poller = RenderPoller(
                render_url=render_cfg.get("url", "https://trading-agent-v1-codex.onrender.com"),
                inbox_dir=render_cfg.get("inbox_dir", "signals/inbox"),
                state_file=render_cfg.get("state_file", "data/render_poll_state.json"),
            )
            self._inbox_processor = InboxProcessor(
                inbox_dir=render_cfg.get("inbox_dir", "signals/inbox"),
                signal_routing=render_cfg.get("signal_routing", {}),
            )
            logger.info("Render webhook polling enabled: %s", render_cfg.get("url"))
        else:
            logger.info("Render webhook polling disabled")

        # ── Watchlist ─────────────────────────────────────────────────────────
        wl = self.cfg.get("watchlists", {})
        self._stocks  = wl.get("stocks",  [])
        self._crypto  = wl.get("crypto",  [])
        self._metals  = wl.get("metals",  [])
        self._futures = wl.get("futures", [])
        self._watchlist = self._stocks + self._crypto + self._metals + self._futures

        # Collect every unique timeframe required across all profiles
        all_tfs: set[str] = set()
        for profile in scan_profiles.values():
            all_tfs.update(profile.get("timeframes", []))
        self._all_timeframes = sorted(all_tfs)
        self._lookback = self.cfg["scanner"]["lookback_bars"]

    # ── Public ────────────────────────────────────────────────────────────────

    def scan_once(self) -> list[MTFSignal]:
        """Run a full MTF scan cycle across all tickers and profiles."""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        logger.info("═══ Scan cycle  %s ═══", ts)
        profiles = list(self.cfg.get("scan_profiles", {}).keys())
        print(
            f"\n[{ts}] "
            f"{len(self._watchlist)} tickers × "
            f"{len(self._all_timeframes)} timeframes × "
            f"{len(profiles)} profiles ({', '.join(profiles)}) …"
        )

        all_signals: list[MTFSignal] = []
        ticker_prices: dict[str, float] = {}

        for ticker in self._watchlist:
            # Fetch data for every required timeframe in one pass
            data_by_tf = self._fetch_all_timeframes(ticker)
            if not data_by_tf:
                continue

            # Capture a reference price
            for df in data_by_tf.values():
                if not df.empty:
                    ticker_prices[ticker] = float(df["close"].iloc[-1])
                    break

            # MTF confluence scan across all configured profiles
            mtf_signals = self._mtf_scanner.scan_all_profiles(ticker, data_by_tf)
            for sig in mtf_signals:
                # Apply learned confidence boosts from trade history
                boost = self._signal_gen._get_boost(sig.rule_name)
                if boost != 0.0:
                    sig.mtf_confidence = round(
                        min(1.0, max(0.0, sig.mtf_confidence + boost)), 3
                    )

                # Filter by min confidence
                if sig.mtf_confidence < self._signal_gen._min_confidence:
                    logger.debug(
                        "MTF signal %s on %s filtered (conf %.2f < %.2f)",
                        sig.rule_name, ticker,
                        sig.mtf_confidence, self._signal_gen._min_confidence,
                    )
                    continue

                all_signals.append(sig)
                print(f"  ⚡  {sig}")
                self._dispatch_alerts(sig)
                self._execute(sig)

        # ── Process TradingView webhook inbox ────────────────────────────────
        tv_signals = self._process_webhook_inbox()
        if tv_signals:
            all_signals.extend(tv_signals)

        # Update fallback paper positions
        if self._paper_trader and ticker_prices:
            self._paper_trader.update_positions(ticker_prices)

        if not all_signals:
            print("  No signals this cycle.")

        logger.info("═══ Cycle complete  %d signals (%d internal, %d webhook) ═══",
                     len(all_signals), len(all_signals) - len(tv_signals), len(tv_signals))
        record_scan(len(all_signals))
        return all_signals

    def run(self) -> None:
        """Start the continuous scheduled agent loop."""
        # Start health check server for container orchestration
        start_health_server(port=int(os.getenv("HEALTH_PORT", "8081")))

        interval = self.cfg["scanner"]["scan_interval_minutes"]
        profiles = list(self.cfg.get("scan_profiles", {}).keys())

        update_status(
            status="running",
            watchlist_size=len(self._watchlist),
            execution_mode=self.cfg["execution"]["mode"],
        )

        print(
            f"\n{'═'*60}\n"
            f"  Trading Agent\n"
            f"  Watchlist  : {', '.join(self._watchlist[:6])}"
            f"{'…' if len(self._watchlist) > 6 else ''}\n"
            f"  Profiles   : {', '.join(profiles)}\n"
            f"  Timeframes : {', '.join(self._all_timeframes)}\n"
            f"  Interval   : every {interval} minutes\n"
            f"  Execution  : {self.cfg['execution']['mode'].upper()}\n"
            f"{'═'*60}\n"
        )

        discord_alert.send_text(
            f"🤖 Trading Agent started | "
            f"{len(self._watchlist)} tickers | "
            f"Profiles: {', '.join(profiles)} | "
            f"every {interval}min"
        )

        scheduler = BlockingScheduler(timezone="UTC")
        scheduler.add_job(
            self.scan_once,
            trigger="interval",
            minutes=interval,
            id="scan",
            next_run_time=datetime.now(timezone.utc),  # run immediately on start
        )

        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            print("\nAgent stopped.")
            if self._paper_trader:
                self._paper_trader.print_report()

    def poll_render(self) -> list[dict]:
        """One-shot poll of Render webhook service. Returns new agent_packets."""
        if not self._render_poller:
            logger.warning("Render poller not configured")
            return []
        return self._render_poller.poll()

    # ── Private ───────────────────────────────────────────────────────────────

    def _process_webhook_inbox(self) -> list[MTFSignal]:
        """
        Poll Render for new events, then process any pending inbox files.
        Returns MTFSignal list from webhook events.
        """
        if not self._render_enabled:
            return []

        tv_signals: list[MTFSignal] = []

        # Step 1: Poll Render for new events → saves to inbox
        if self._render_poller:
            try:
                new_packets = self._render_poller.poll()
                if new_packets:
                    logger.info("Polled %d new events from Render", len(new_packets))
            except Exception as exc:
                logger.error("Render poll failed: %s", exc)

        # Step 2: Process inbox files → convert to signals
        if self._inbox_processor:
            try:
                inbox_signals = self._inbox_processor.process()
                for isig in inbox_signals:
                    mtf_sig = isig.to_mtf_signal()
                    print(f"  📡 TV: {mtf_sig}")

                    # Route based on confluence level
                    if isig.action == "execute":
                        self._dispatch_alerts(mtf_sig)
                        self._execute(mtf_sig)
                        logger.info("TV signal EXECUTED: %s %s", isig.symbol, isig.bias)
                    else:
                        # Alert only — no execution
                        self._dispatch_alerts(mtf_sig)
                        logger.info("TV signal ALERTED: %s %s (action=%s)",
                                    isig.symbol, isig.bias, isig.action)

                    tv_signals.append(mtf_sig)
            except Exception as exc:
                logger.error("Inbox processing failed: %s", exc)

        return tv_signals

    def _fetch_all_timeframes(self, ticker: str) -> dict:
        """Fetch OHLCV data for every required timeframe for a single ticker."""
        data_by_tf = {}
        for tf in self._all_timeframes:
            df = self._provider.get_ohlcv(ticker, tf, bars=self._lookback)
            if df is not None and not df.empty:
                data_by_tf[tf] = df
        return data_by_tf

    def _dispatch_alerts(self, mtf_sig: MTFSignal) -> None:
        signal = mtf_sig.to_signal()
        alert_cfg = self.cfg.get("alerts", {})
        if alert_cfg.get("discord", {}).get("enabled"):
            discord_alert.send_signal(signal)
        if alert_cfg.get("email", {}).get("enabled"):
            email_alert.send_signal(signal)

    def _execute(self, mtf_sig: MTFSignal) -> None:
        """Route to Alpaca broker (paper or live) or fallback PaperTrader."""
        exec_cfg = self.cfg["execution"]

        if self._alpaca_broker:
            try:
                acc   = self._alpaca_broker.get_account()
                price = list(mtf_sig.prices.values())[0]
                qty   = max(1, int((acc["equity"] * exec_cfg["max_position_pct"]) / price))
            except Exception:
                qty = 1

            self._alpaca_broker.order_from_signal(
                signal=mtf_sig.to_signal(),
                qty=qty,
                stop_loss_pct=exec_cfg["stop_loss_pct"],
                take_profit_pct=exec_cfg["take_profit_pct"],
            )

        elif self._paper_trader:
            self._paper_trader.process_signal(mtf_sig.to_signal())

    @staticmethod
    def _setup_logging() -> None:
        log_fmt  = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        date_fmt = "%Y-%m-%d %H:%M:%S"

        root = logging.getLogger()
        root.setLevel(logging.INFO)

        # ── Console handler ────────────────────────────────────────────────
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(log_fmt, datefmt="%H:%M:%S"))
        root.addHandler(console)

        # ── Rotating file handler → logs/agent.log (10 MB × 5 backups) ───
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "agent.log",
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter(log_fmt, datefmt=date_fmt))
        root.addHandler(file_handler)

        # ── Silence noisy third-party loggers ─────────────────────────────
        for lib in ("yfinance", "urllib3", "peewee", "apscheduler", "hpack", "httpx"):
            logging.getLogger(lib).setLevel(logging.WARNING)

"""
Backtesting engine.

Runs the same rule-based scanner against historical OHLCV data and reports
performance metrics using vectorbt (if installed) or a built-in simple
portfolio simulator as fallback.

Usage (standalone):
    from backtesting.engine import Backtester
    bt = Backtester(rules_path="config/rules.yaml")
    report = bt.run(ticker="AAPL", timeframe="1d", lookback_bars=500)
    bt.print_report(report)

CLI:
    python main.py backtest --ticker AAPL --timeframe 1d --bars 500
    python main.py backtest --ticker AAPL --timeframe 1d --all-rules
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import numpy as np

from analysis.indicators import add_all_indicators
from analysis.patterns   import add_all_patterns
from analysis.scanner    import Scanner, Signal

logger = logging.getLogger(__name__)


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class Trade:
    rule_name:  str
    signal:     str        # "buy" | "sell"
    entry_date: str
    exit_date:  str
    entry_price: float
    exit_price:  float
    pnl_pct:    float      # % return
    pnl_abs:    float      # dollar return per share
    win:        bool


@dataclass
class BacktestReport:
    ticker:        str
    timeframe:     str
    rule_name:     str
    total_trades:  int
    wins:          int
    losses:        int
    win_rate:      float
    avg_win_pct:   float
    avg_loss_pct:  float
    profit_factor: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio:  float
    trades:        list[Trade] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"\n{'═'*55}\n"
            f"  Backtest: {self.ticker} [{self.timeframe}]  rule={self.rule_name}\n"
            f"{'─'*55}\n"
            f"  Trades        : {self.total_trades}  "
            f"(W:{self.wins} / L:{self.losses})\n"
            f"  Win Rate      : {self.win_rate:.1%}\n"
            f"  Avg Win       : +{self.avg_win_pct:.2f}%\n"
            f"  Avg Loss      : {self.avg_loss_pct:.2f}%\n"
            f"  Profit Factor : {self.profit_factor:.2f}\n"
            f"  Total Return  : {self.total_return_pct:+.2f}%\n"
            f"  Max Drawdown  : {self.max_drawdown_pct:.2f}%\n"
            f"  Sharpe Ratio  : {self.sharpe_ratio:.2f}\n"
            f"{'═'*55}\n"
        )


# ── Backtester ────────────────────────────────────────────────────────────────

class Backtester:
    """
    Walk-forward backtester that replays the scanner bar-by-bar.

    Parameters
    ----------
    rules_path : str
        Path to config/rules.yaml
    stop_loss_pct : float
        Stop loss as a fraction of entry price (e.g. 0.02 = 2%)
    take_profit_pct : float
        Take profit as a fraction (e.g. 0.04 = 4%)
    commission_pct : float
        Round-trip commission fraction (e.g. 0.001 = 0.1%)
    """

    def __init__(
        self,
        rules_path: str = "config/rules.yaml",
        stop_loss_pct:   float = 0.02,
        take_profit_pct: float = 0.04,
        commission_pct:  float = 0.001,
    ):
        self._scanner         = Scanner(rules_path)
        self._sl_pct          = stop_loss_pct
        self._tp_pct          = take_profit_pct
        self._commission_pct  = commission_pct

    # ── Public ────────────────────────────────────────────────────────────────

    def run(
        self,
        df: pd.DataFrame,
        ticker: str,
        timeframe: str,
        rule_name: Optional[str] = None,
        warmup_bars: int = 50,
    ) -> list[BacktestReport]:
        """
        Run the backtest on a prepared OHLCV DataFrame.

        Parameters
        ----------
        df : pd.DataFrame
            OHLCV data with columns: open, high, low, close, volume.
        ticker : str
            Ticker symbol (for reporting only).
        timeframe : str
            Timeframe label (for reporting only).
        rule_name : str, optional
            If given, only backtest this rule. Otherwise backtest all rules.
        warmup_bars : int
            Number of bars to skip at the start (let indicators warm up).

        Returns
        -------
        list[BacktestReport]
            One report per rule tested.
        """
        # Enrich with indicators + patterns
        df = add_all_indicators(df.copy())
        df = add_all_patterns(df.copy())

        reports = []
        n = len(df)

        # Determine which rules to test
        all_rules = [r["name"] for r in self._scanner.rules]
        rules_to_test = [rule_name] if rule_name else all_rules

        for rname in rules_to_test:
            trades = self._simulate_rule(df, ticker, timeframe, rname, warmup_bars, n)
            report = self._build_report(ticker, timeframe, rname, trades)
            reports.append(report)

        return reports

    def run_with_vectorbt(
        self,
        df: pd.DataFrame,
        ticker: str,
        timeframe: str,
        rule_name: Optional[str] = None,
        warmup_bars: int = 50,
    ) -> list[BacktestReport]:
        """
        Run using vectorbt for richer stats (Sharpe, drawdown curves, etc.).
        Falls back to self.run() if vectorbt is not installed.
        """
        try:
            import vectorbt as vbt
        except ImportError:
            logger.warning(
                "vectorbt not installed — falling back to built-in engine. "
                "Install with: pip install vectorbt"
            )
            return self.run(df, ticker, timeframe, rule_name, warmup_bars)

        df = add_all_indicators(df.copy())
        df = add_all_patterns(df.copy())

        all_rules = [r["name"] for r in self._scanner.rules]
        rules_to_test = [rule_name] if rule_name else all_rules
        reports = []

        close = df["close"]

        for rname in rules_to_test:
            entries, exits = self._build_signal_arrays(df, ticker, timeframe, rname, warmup_bars)

            if entries.sum() == 0:
                logger.debug("No entry signals for rule %s on %s %s", rname, ticker, timeframe)
                continue

            try:
                pf = vbt.Portfolio.from_signals(
                    close=close,
                    entries=entries,
                    exits=exits,
                    sl_stop=self._sl_pct,
                    tp_stop=self._tp_pct,
                    fees=self._commission_pct,
                    freq=timeframe,
                )

                stats = pf.stats()

                # Map vbt stats → BacktestReport
                n_trades    = int(stats.get("Total Trades", 0))
                win_rate    = float(stats.get("Win Rate [%]", 0.0)) / 100
                total_ret   = float(stats.get("Total Return [%]", 0.0))
                max_dd      = float(stats.get("Max Drawdown [%]", 0.0))
                sharpe      = float(stats.get("Sharpe Ratio",    0.0))

                wins   = round(n_trades * win_rate)
                losses = n_trades - wins

                # Avg win / loss from trade records
                trade_records = pf.trades.records_readable
                if not trade_records.empty:
                    win_mask  = trade_records["PnL"] > 0
                    avg_win   = trade_records.loc[win_mask,  "Return [%]"].mean() if win_mask.any()  else 0.0
                    avg_loss  = trade_records.loc[~win_mask, "Return [%]"].mean() if (~win_mask).any() else 0.0
                else:
                    avg_win = avg_loss = 0.0

                gross_profit = trade_records.loc[trade_records["PnL"] > 0, "PnL"].sum() if not trade_records.empty else 0
                gross_loss   = abs(trade_records.loc[trade_records["PnL"] < 0, "PnL"].sum()) if not trade_records.empty else 0
                pf_ratio     = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

                report = BacktestReport(
                    ticker=ticker,
                    timeframe=timeframe,
                    rule_name=rname,
                    total_trades=n_trades,
                    wins=wins,
                    losses=losses,
                    win_rate=win_rate,
                    avg_win_pct=avg_win,
                    avg_loss_pct=avg_loss,
                    profit_factor=pf_ratio,
                    total_return_pct=total_ret,
                    max_drawdown_pct=max_dd,
                    sharpe_ratio=sharpe,
                )
                reports.append(report)

            except Exception as exc:
                logger.warning("vectorbt error for %s %s %s: %s", ticker, timeframe, rname, exc)
                # Fall back to built-in for this rule
                trades = self._simulate_rule(df, ticker, timeframe, rname, warmup_bars, len(df))
                reports.append(self._build_report(ticker, timeframe, rname, trades))

        return reports

    @staticmethod
    def print_report(report: BacktestReport) -> None:
        print(report)

    @staticmethod
    def print_summary(reports: list[BacktestReport]) -> None:
        """Print a ranked summary table of all rules tested."""
        if not reports:
            print("No backtest results.")
            return

        print(f"\n{'═'*75}")
        print(f"  {'RULE':<30} {'TF':<6} {'TRADES':>6} {'WIN%':>6} {'TOT RET':>8} {'PF':>6} {'SHARPE':>7}")
        print(f"{'─'*75}")

        ranked = sorted(reports, key=lambda r: r.total_return_pct, reverse=True)
        for r in ranked:
            pf_str  = f"{r.profit_factor:.2f}" if r.profit_factor < 999 else "∞"
            print(
                f"  {r.rule_name:<30} {r.timeframe:<6} "
                f"{r.total_trades:>6} {r.win_rate:>6.1%} "
                f"{r.total_return_pct:>+8.2f}% {pf_str:>6} {r.sharpe_ratio:>7.2f}"
            )
        print(f"{'═'*75}\n")

    # ── Private ───────────────────────────────────────────────────────────────

    def _simulate_rule(
        self,
        df: pd.DataFrame,
        ticker: str,
        timeframe: str,
        rule_name: str,
        warmup_bars: int,
        n: int,
    ) -> list[Trade]:
        """Walk forward bar-by-bar, enter on signal, exit on SL/TP or next signal."""
        trades: list[Trade] = []
        in_trade   = False
        entry_price = 0.0
        entry_idx   = 0
        entry_date  = ""
        signal_dir  = ""

        for i in range(warmup_bars, n):
            row   = df.iloc[i]
            close = float(row["close"])
            high  = float(row["high"])
            low   = float(row["low"])

            # ── Exit logic ──────────────────────────────────────────────
            if in_trade:
                sl = (
                    entry_price * (1 - self._sl_pct) if signal_dir == "buy"
                    else entry_price * (1 + self._sl_pct)
                )
                tp = (
                    entry_price * (1 + self._tp_pct) if signal_dir == "buy"
                    else entry_price * (1 - self._tp_pct)
                )

                hit_sl = (signal_dir == "buy" and low  <= sl) or \
                         (signal_dir == "sell" and high >= sl)
                hit_tp = (signal_dir == "buy" and high >= tp) or \
                         (signal_dir == "sell" and low  <= tp)

                if hit_sl or hit_tp:
                    exit_price = sl if hit_sl else tp
                    pnl = (
                        (exit_price - entry_price) / entry_price
                        if signal_dir == "buy"
                        else (entry_price - exit_price) / entry_price
                    )
                    pnl -= self._commission_pct
                    trades.append(Trade(
                        rule_name=rule_name,
                        signal=signal_dir,
                        entry_date=entry_date,
                        exit_date=str(df.index[i]),
                        entry_price=entry_price,
                        exit_price=exit_price,
                        pnl_pct=pnl * 100,
                        pnl_abs=pnl * entry_price,
                        win=pnl > 0,
                    ))
                    in_trade = False
                    continue  # don't enter a new trade on the same bar

            # ── Entry logic ──────────────────────────────────────────────
            if not in_trade:
                slice_df = df.iloc[: i + 1]
                try:
                    signals = self._scanner.scan(ticker, timeframe, slice_df)
                except Exception:
                    continue

                for sig in signals:
                    if sig.rule_name != rule_name:
                        continue
                    in_trade    = True
                    entry_price = close * (1 + self._commission_pct / 2)
                    entry_idx   = i
                    entry_date  = str(df.index[i])
                    signal_dir  = sig.signal
                    break

        return trades

    def _build_signal_arrays(
        self,
        df: pd.DataFrame,
        ticker: str,
        timeframe: str,
        rule_name: str,
        warmup_bars: int,
    ):
        """Build boolean entry/exit arrays for vectorbt."""
        n = len(df)
        entries = np.zeros(n, dtype=bool)
        exits   = np.zeros(n, dtype=bool)

        for i in range(warmup_bars, n):
            slice_df = df.iloc[: i + 1]
            try:
                signals = self._scanner.scan(ticker, timeframe, slice_df)
            except Exception:
                continue

            for sig in signals:
                if sig.rule_name != rule_name:
                    continue
                if sig.signal == "buy":
                    entries[i] = True
                else:
                    exits[i] = True
                break  # one signal per bar per rule

        return pd.Series(entries, index=df.index), pd.Series(exits, index=df.index)

    @staticmethod
    def _build_report(
        ticker: str,
        timeframe: str,
        rule_name: str,
        trades: list[Trade],
    ) -> BacktestReport:
        if not trades:
            return BacktestReport(
                ticker=ticker, timeframe=timeframe, rule_name=rule_name,
                total_trades=0, wins=0, losses=0, win_rate=0.0,
                avg_win_pct=0.0, avg_loss_pct=0.0, profit_factor=0.0,
                total_return_pct=0.0, max_drawdown_pct=0.0, sharpe_ratio=0.0,
                trades=[],
            )

        wins   = [t for t in trades if t.win]
        losses = [t for t in trades if not t.win]

        win_rate    = len(wins) / len(trades)
        avg_win     = sum(t.pnl_pct for t in wins)   / len(wins)   if wins   else 0.0
        avg_loss    = sum(t.pnl_pct for t in losses) / len(losses) if losses else 0.0
        gross_win   = sum(t.pnl_pct for t in wins)
        gross_loss  = abs(sum(t.pnl_pct for t in losses))
        pf          = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
        total_ret   = sum(t.pnl_pct for t in trades)

        # Max drawdown via cumulative equity curve
        equity = np.cumprod([1 + t.pnl_pct / 100 for t in trades])
        peak   = np.maximum.accumulate(equity)
        dd     = (equity - peak) / peak * 100
        max_dd = float(abs(dd.min())) if len(dd) > 0 else 0.0

        # Annualised Sharpe (approximate, no risk-free rate)
        rets = np.array([t.pnl_pct / 100 for t in trades])
        sharpe = (float(rets.mean() / rets.std()) * np.sqrt(252)) if rets.std() > 0 else 0.0

        return BacktestReport(
            ticker=ticker, timeframe=timeframe, rule_name=rule_name,
            total_trades=len(trades),
            wins=len(wins),
            losses=len(losses),
            win_rate=win_rate,
            avg_win_pct=avg_win,
            avg_loss_pct=avg_loss,
            profit_factor=pf,
            total_return_pct=total_ret,
            max_drawdown_pct=max_dd,
            sharpe_ratio=sharpe,
            trades=trades,
        )

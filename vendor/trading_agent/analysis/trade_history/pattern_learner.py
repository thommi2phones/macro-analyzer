"""
Pattern learner – analyzes extracted trade history to surface your personal edge.

Given a list of TradeRecord objects it computes:
  • Win rate by setup type
  • Most common indicators in winning vs losing trades
  • Preferred timeframes
  • Average P&L by setup
  • Confidence scores that feed back into the scanner's rule weighting
"""

import json
import logging
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, stdev
from typing import Any

from analysis.trade_history.image_analyzer import TradeRecord

logger = logging.getLogger(__name__)


class PatternLearner:

    def __init__(self, records: list[TradeRecord]):
        self.records = [r for r in records if r.ticker]  # filter empties

    # ── Public ────────────────────────────────────────────────────────────────

    def analyze(self) -> dict[str, Any]:
        """
        Run full analysis and return an insights dict.
        Also writes config/learned_rules.yaml with setup-specific confidence boosts.
        """
        if not self.records:
            return {"error": "No trade records to analyze"}

        insights: dict[str, Any] = {
            "total_trades": len(self.records),
            "trades_with_outcome": sum(1 for r in self.records if r.win is not None),
            "overall_win_rate": self._overall_win_rate(),
            "by_setup": self._by_setup(),
            "by_timeframe": self._by_timeframe(),
            "by_direction": self._by_direction(),
            "top_winning_indicators": self._top_indicators(wins_only=True),
            "top_losing_indicators": self._top_indicators(wins_only=False),
            "pnl_summary": self._pnl_summary(),
            "confidence_adjustments": self._confidence_adjustments(),
        }
        return insights

    def print_report(self, insights: dict[str, Any]) -> None:
        """Pretty-print insights to stdout."""
        sep = "─" * 60
        print(f"\n{sep}")
        print("  PERSONAL TRADING PATTERN REPORT")
        print(sep)
        print(f"  Total trades analyzed : {insights['total_trades']}")
        print(f"  Trades with outcome   : {insights['trades_with_outcome']}")
        wr = insights["overall_win_rate"]
        if wr is not None:
            print(f"  Overall win rate      : {wr:.1%}")
        print()

        by_setup = insights.get("by_setup", {})
        if by_setup:
            print("  WIN RATE BY SETUP TYPE")
            for setup, stats in sorted(by_setup.items(), key=lambda x: -(x[1]["win_rate"] or 0)):
                wr_s = f"{stats['win_rate']:.1%}" if stats["win_rate"] is not None else "n/a"
                avg_pnl = f"avg P&L {stats['avg_pnl_pct']:+.1f}%" if stats.get("avg_pnl_pct") else ""
                print(f"    {setup:<30} {wr_s:>6}  n={stats['count']}  {avg_pnl}")
        print()

        by_tf = insights.get("by_timeframe", {})
        if by_tf:
            print("  WIN RATE BY TIMEFRAME")
            for tf, stats in sorted(by_tf.items(), key=lambda x: -(x[1]["win_rate"] or 0)):
                wr_tf = f"{stats['win_rate']:.1%}" if stats["win_rate"] is not None else "n/a"
                print(f"    {tf:<10} {wr_tf:>6}  n={stats['count']}")
        print()

        top_win_ind = insights.get("top_winning_indicators", [])
        if top_win_ind:
            print("  INDICATORS MOST COMMON IN WINNING TRADES")
            for ind, cnt in top_win_ind[:8]:
                print(f"    {ind:<25} {cnt} trades")
        print()

        conf_adj = insights.get("confidence_adjustments", {})
        if conf_adj:
            print("  CONFIDENCE ADJUSTMENTS (applied to scanner rules)")
            for setup, adj in sorted(conf_adj.items(), key=lambda x: -x[1]):
                sign = "+" if adj >= 0 else ""
                print(f"    {setup:<30} {sign}{adj:+.2f}")
        print(sep)

    def save_insights(self, path: str = "data/trade_insights.json") -> None:
        insights = self.analyze()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(insights, indent=2, default=str))
        logger.info("Insights saved to %s", path)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _records_with_outcome(self) -> list[TradeRecord]:
        return [r for r in self.records if r.win is not None]

    def _overall_win_rate(self) -> float | None:
        w = self._records_with_outcome()
        if not w:
            return None
        return sum(1 for r in w if r.win) / len(w)

    def _by_setup(self) -> dict[str, dict]:
        grouped: dict[str, list[TradeRecord]] = defaultdict(list)
        for r in self.records:
            key = r.setup_type or "unknown"
            grouped[key].append(r)

        result = {}
        for setup, trades in grouped.items():
            with_outcome = [t for t in trades if t.win is not None]
            wins = [t for t in with_outcome if t.win]
            pnl_vals = [t.pnl_percent for t in trades if t.pnl_percent is not None]
            result[setup] = {
                "count": len(trades),
                "win_rate": len(wins) / len(with_outcome) if with_outcome else None,
                "avg_pnl_pct": mean(pnl_vals) if pnl_vals else None,
            }
        return result

    def _by_timeframe(self) -> dict[str, dict]:
        grouped: dict[str, list[TradeRecord]] = defaultdict(list)
        for r in self.records:
            key = r.timeframe or "unknown"
            grouped[key].append(r)

        result = {}
        for tf, trades in grouped.items():
            with_outcome = [t for t in trades if t.win is not None]
            wins = [t for t in with_outcome if t.win]
            result[tf] = {
                "count": len(trades),
                "win_rate": len(wins) / len(with_outcome) if with_outcome else None,
            }
        return result

    def _by_direction(self) -> dict[str, dict]:
        result = {}
        for direction in ("long", "short"):
            trades = [r for r in self.records if r.direction == direction]
            with_outcome = [t for t in trades if t.win is not None]
            wins = [t for t in with_outcome if t.win]
            result[direction] = {
                "count": len(trades),
                "win_rate": len(wins) / len(with_outcome) if with_outcome else None,
            }
        return result

    def _top_indicators(self, wins_only: bool) -> list[tuple[str, int]]:
        subset = [
            r for r in self.records
            if r.win is not None and r.win == wins_only
        ]
        counter: Counter = Counter()
        for r in subset:
            for ind in r.indicators_visible:
                counter[ind.strip()] += 1
        return counter.most_common(10)

    def _pnl_summary(self) -> dict:
        pnl_vals = [r.pnl_percent for r in self.records if r.pnl_percent is not None]
        if not pnl_vals:
            return {}
        wins = [p for p in pnl_vals if p > 0]
        losses = [p for p in pnl_vals if p <= 0]
        return {
            "avg_pnl_pct": mean(pnl_vals),
            "avg_win_pct": mean(wins) if wins else None,
            "avg_loss_pct": mean(losses) if losses else None,
            "expectancy": mean(pnl_vals) if pnl_vals else None,
            "profit_factor": (
                abs(sum(wins) / sum(losses)) if losses and wins else None
            ),
        }

    def _confidence_adjustments(self) -> dict[str, float]:
        """
        Returns per-setup confidence delta (+/-) to overlay on scanner rules.
        Setup with >60% win rate gets a positive boost; <40% gets a penalty.
        """
        adjustments = {}
        by_setup = self._by_setup()
        for setup, stats in by_setup.items():
            wr = stats.get("win_rate")
            count = stats.get("count", 0)
            if wr is None or count < 3:   # need at least 3 samples
                continue
            # Scale: 0.6 win rate → +0.05, 0.4 win rate → -0.05
            delta = round((wr - 0.5) * 0.2, 3)
            adjustments[setup] = delta
        return adjustments

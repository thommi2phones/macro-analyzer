"""
Multi-Timeframe (MTF) Scanner with majority-vote confluence.

The core insight: a move originates on a lower timeframe and dissipates
as you go higher. A signal that shows on 3 of 5 timeframes is real but
fading — we still want it, just with proportionally reduced confidence.

Algorithm per ticker per rule:
  1. Run the rule independently on every configured timeframe
  2. Count how many TFs fired   (triggered_count)
  3. Count how many TFs had data (available_count)
  4. ratio = triggered_count / available_count
  5. If ratio >= required_majority → emit MTFSignal
     - mtf_confidence = base_confidence × ratio
     - This naturally rewards signals that agree across more timeframes

Two built-in scan profiles (configurable in settings.yaml):
  • macro  — D / W / M    — for long-term trend positioning
  • swing  — 4h / 12h / D / 3d / W  — for swing trade entries
  • intra  — 15m / 1h / 4h          — for intraday / short-swing
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from analysis.scanner import Scanner, Signal

logger = logging.getLogger(__name__)


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class MTFSignal:
    ticker: str
    rule_name: str
    signal: str                    # "buy" | "sell"
    base_confidence: float
    mtf_confidence: float          # base_confidence × (triggered / available)
    majority_ratio: float          # e.g. 0.6 → 3/5 TFs agreed
    timeframes_triggered: list[str]
    timeframes_checked: list[str]
    prices: dict[str, float]       # {tf: close_price}
    rsi_values: dict[str, float]   # {tf: rsi}  for context
    description: str
    profile: str                   # "macro" | "swing" | "intra"
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def __str__(self) -> str:
        direction = "🟢 BUY" if self.signal == "buy" else "🔴 SELL"
        tf_str = "/".join(self.timeframes_triggered)
        return (
            f"{direction} {self.ticker} [{self.profile}] "
            f"{self.rule_name}  "
            f"TFs: {tf_str}/{len(self.timeframes_checked)}  "
            f"conf={self.mtf_confidence:.0%}"
        )

    def to_signal(self) -> Signal:
        """Convert to a plain Signal for alerting compatibility."""
        price = list(self.prices.values())[0] if self.prices else 0.0
        rsi   = list(self.rsi_values.values())[0] if self.rsi_values else None
        tf_label = "+".join(self.timeframes_triggered)
        return Signal(
            ticker=self.ticker,
            timeframe=tf_label,
            rule_name=self.rule_name,
            signal=self.signal,
            confidence=self.mtf_confidence,
            price=price,
            rsi=rsi,
            description=(
                f"[{self.profile.upper()} MTF {self.majority_ratio:.0%}] "
                f"{self.description}"
            ),
            timestamp=self.timestamp,
        )


# ── Scanner ───────────────────────────────────────────────────────────────────

class MTFScanner:
    """
    Multi-timeframe scanner.

    Parameters
    ----------
    scanner : Scanner
        The single-timeframe rule engine.
    profiles : dict
        Loaded from settings.yaml `scan_profiles` section.
        Example:
            {
              "macro": {"timeframes": ["1d","1wk","1mo"], "required_majority": 0.67},
              "swing": {"timeframes": ["4h","12h","1d","3d","1wk"], "required_majority": 0.60},
            }
    """

    def __init__(self, scanner: Scanner, profiles: dict):
        self._scanner  = scanner
        self._profiles = profiles

    # ── Public ────────────────────────────────────────────────────────────────

    def scan_all_profiles(
        self,
        ticker: str,
        data_by_tf: dict[str, pd.DataFrame],
    ) -> list[MTFSignal]:
        """Run all configured scan profiles for a ticker."""
        results: list[MTFSignal] = []
        for profile_name in self._profiles:
            results.extend(self.scan_profile(ticker, profile_name, data_by_tf))
        return results

    def scan_profile(
        self,
        ticker: str,
        profile_name: str,
        data_by_tf: dict[str, pd.DataFrame],
    ) -> list[MTFSignal]:
        """
        Run a single scan profile with MTF confluence.

        Returns signals that meet the majority threshold.
        Signals with lower ratios are still captured but filtered;
        lower the required_majority in config to surface them.
        """
        profile = self._profiles.get(profile_name)
        if not profile:
            logger.warning("Unknown profile: %s", profile_name)
            return []

        timeframes        = profile["timeframes"]
        required_majority = float(profile.get("required_majority", 0.60))

        # ── Step 1: Collect raw signals per (rule, tf) ─────────────────────
        # rule_name → {tf → Signal}
        rule_hits: dict[str, dict[str, Signal]] = defaultdict(dict)
        available_tfs: list[str] = []

        for tf in timeframes:
            df = data_by_tf.get(tf)
            if df is None or df.empty:
                logger.debug("%s %s: no data for %s, skipping TF", ticker, profile_name, tf)
                continue
            available_tfs.append(tf)

            try:
                raw_signals = self._scanner.scan(ticker, tf, df)
            except Exception as exc:
                logger.warning("Scanner error %s %s %s: %s", ticker, tf, profile_name, exc)
                continue

            for sig in raw_signals:
                rule_hits[sig.rule_name][tf] = sig

        if not available_tfs:
            return []

        # ── Step 2: Majority vote per rule ─────────────────────────────────
        results: list[MTFSignal] = []

        for rule_name, tf_signals in rule_hits.items():
            triggered_tfs = list(tf_signals.keys())
            ratio = len(triggered_tfs) / len(available_tfs)

            if ratio < required_majority:
                logger.debug(
                    "%s [%s] %s: ratio %.0f%% < required %.0f%% — skipped",
                    ticker, profile_name, rule_name,
                    ratio * 100, required_majority * 100,
                )
                continue

            # Use the first (usually lowest) triggered TF's signal as base
            sample_sig = next(iter(tf_signals.values()))

            mtf_sig = MTFSignal(
                ticker=ticker,
                rule_name=rule_name,
                signal=sample_sig.signal,
                base_confidence=sample_sig.confidence,
                mtf_confidence=round(sample_sig.confidence * ratio, 3),
                majority_ratio=round(ratio, 3),
                timeframes_triggered=triggered_tfs,
                timeframes_checked=available_tfs,
                prices={tf: sig.price for tf, sig in tf_signals.items()},
                rsi_values={
                    tf: sig.rsi for tf, sig in tf_signals.items()
                    if sig.rsi is not None
                },
                description=sample_sig.description,
                profile=profile_name,
            )
            results.append(mtf_sig)
            logger.info("%s", mtf_sig)

        return results

    def scan_profile_summary(
        self,
        ticker: str,
        profile_name: str,
        data_by_tf: dict[str, pd.DataFrame],
    ) -> dict:
        """
        Returns a diagnostic dict showing all rules evaluated and their
        per-TF hit status — useful for debugging why a signal did/didn't fire.
        """
        profile    = self._profiles.get(profile_name, {})
        timeframes = profile.get("timeframes", [])

        summary = {"ticker": ticker, "profile": profile_name, "rules": {}}

        for tf in timeframes:
            df = data_by_tf.get(tf)
            if df is None or df.empty:
                continue
            sigs = self._scanner.scan(ticker, tf, df)
            for sig in sigs:
                if sig.rule_name not in summary["rules"]:
                    summary["rules"][sig.rule_name] = {"signal": sig.signal, "tfs": []}
                summary["rules"][sig.rule_name]["tfs"].append(tf)

        return summary

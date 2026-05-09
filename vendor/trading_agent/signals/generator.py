"""
Signal generator.

Wraps the Scanner and optionally applies confidence adjustments derived
from the user's historical trade analysis.
"""

import json
import logging
from pathlib import Path

import pandas as pd

from analysis.scanner import Scanner, Signal
from data.providers.base import DataProvider

logger = logging.getLogger(__name__)


class SignalGenerator:

    def __init__(
        self,
        scanner: Scanner,
        insights_path: str = "data/trade_insights.json",
        min_confidence: float = 0.55,
    ):
        self._scanner = scanner
        self._min_confidence = min_confidence
        self._confidence_adjustments: dict[str, float] = {}
        self._load_insights(insights_path)

    # ── Public ────────────────────────────────────────────────────────────────

    def generate(
        self,
        ticker: str,
        timeframe: str,
        df: pd.DataFrame,
    ) -> list[Signal]:
        """
        Scan df for signals, apply learned confidence adjustments,
        and filter by minimum confidence threshold.
        """
        raw_signals = self._scanner.scan(ticker, timeframe, df)

        adjusted = []
        for sig in raw_signals:
            boost = self._get_boost(sig.rule_name)
            final_conf = min(1.0, max(0.0, sig.confidence + boost))
            if final_conf < self._min_confidence:
                logger.debug(
                    "Signal %s on %s filtered out (conf %.2f < %.2f)",
                    sig.rule_name, ticker, final_conf, self._min_confidence,
                )
                continue
            # Return a new Signal with adjusted confidence
            adjusted.append(
                Signal(
                    ticker=sig.ticker,
                    timeframe=sig.timeframe,
                    rule_name=sig.rule_name,
                    signal=sig.signal,
                    confidence=round(final_conf, 3),
                    price=sig.price,
                    rsi=sig.rsi,
                    description=sig.description,
                    timestamp=sig.timestamp,
                )
            )

        return adjusted

    # ── Private ───────────────────────────────────────────────────────────────

    def _load_insights(self, path: str) -> None:
        insights_file = Path(path)
        if not insights_file.exists():
            logger.info("No trade insights file found at %s – running without boosts", path)
            return
        try:
            data = json.loads(insights_file.read_text())
            self._confidence_adjustments = data.get("confidence_adjustments", {})
            logger.info(
                "Loaded %d confidence adjustments from trade history",
                len(self._confidence_adjustments),
            )
        except Exception as exc:
            logger.warning("Could not load insights from %s: %s", path, exc)

    def _get_boost(self, rule_name: str) -> float:
        """
        Look up a confidence boost by rule name or by partial match
        against known setup types from trade history.
        """
        # Exact match first
        if rule_name in self._confidence_adjustments:
            return self._confidence_adjustments[rule_name]

        # Partial match – e.g. setup_type "breakout" → rule "Breakout with Volume"
        rule_lower = rule_name.lower()
        for setup, delta in self._confidence_adjustments.items():
            if setup.lower() in rule_lower or rule_lower in setup.lower():
                return delta

        return 0.0

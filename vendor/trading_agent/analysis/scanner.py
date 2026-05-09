"""
Rule-based scanner.

Loads rules from config/rules.yaml and evaluates each rule's conditions
against the latest bar of an OHLCV + indicator DataFrame.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import yaml

from analysis.indicators import add_all_indicators
from analysis.patterns import add_all_patterns

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    ticker: str
    timeframe: str
    rule_name: str
    signal: str          # "buy" | "sell"
    confidence: float
    price: float
    rsi: float | None
    description: str
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def __str__(self) -> str:
        direction = "🟢 BUY" if self.signal == "buy" else "🔴 SELL"
        rsi_str = f"RSI={self.rsi:.1f}" if self.rsi else ""
        return (
            f"{direction} {self.ticker} @ ${self.price:.4g} "
            f"[{self.timeframe}] {self.rule_name} "
            f"conf={self.confidence:.0%} {rsi_str}"
        )


class Scanner:

    def __init__(self, rules_path: str = "config/rules.yaml"):
        with open(rules_path) as f:
            data = yaml.safe_load(f)
        self.rules: list[dict] = data.get("rules", [])
        logger.info("Loaded %d scan rules from %s", len(self.rules), rules_path)

    # ── Public API ────────────────────────────────────────────────────────────

    def scan(
        self,
        ticker: str,
        timeframe: str,
        df: pd.DataFrame,
    ) -> list[Signal]:
        """
        Evaluate all rules against the last bar of df.
        Returns a list of triggered Signals.
        """
        # Prepare data
        df = add_all_indicators(df)
        df = add_all_patterns(df)

        triggered = []
        for rule in self.rules:
            # Skip rules not configured for this timeframe
            allowed_tfs = rule.get("timeframes")
            if allowed_tfs and timeframe not in allowed_tfs:
                continue

            try:
                if self._evaluate_rule(rule, df):
                    sig = self._build_signal(rule, ticker, timeframe, df)
                    triggered.append(sig)
            except Exception as exc:
                logger.debug("Rule %s evaluation error on %s: %s", rule["name"], ticker, exc)

        return triggered

    # ── Rule evaluation ───────────────────────────────────────────────────────

    def _evaluate_rule(self, rule: dict, df: pd.DataFrame) -> bool:
        conditions = rule.get("conditions", [])
        return all(self._evaluate_condition(c, df) for c in conditions)

    def _evaluate_condition(self, cond: dict, df: pd.DataFrame) -> bool:
        ctype = cond["type"]
        row = df.iloc[-1]   # latest bar

        if ctype == "threshold":
            return self._check_threshold(cond, row)

        if ctype == "price_vs_ind":
            return self._check_price_vs_ind(cond, row)

        if ctype == "cross":
            return self._check_cross(cond, df)

        if ctype == "volume_spike":
            return self._check_volume_spike(cond, row)

        if ctype == "breakout":
            return self._check_breakout(cond, df)

        logger.warning("Unknown condition type: %s", ctype)
        return False

    # ── Condition implementations ─────────────────────────────────────────────

    @staticmethod
    def _get_value(row: pd.Series, key: str) -> float:
        """Resolve 'price' → row['close'], or any indicator column."""
        name = "close" if key == "price" else key
        val = row.get(name)
        if val is None or (isinstance(val, float) and pd.isna(val)):
            raise ValueError(f"Indicator '{key}' not found or NaN")
        return float(val)

    def _check_threshold(self, cond: dict, row: pd.Series) -> bool:
        ind_val = self._get_value(row, cond["indicator"])
        threshold = float(cond["value"])
        return _compare(ind_val, cond["operator"], threshold)

    def _check_price_vs_ind(self, cond: dict, row: pd.Series) -> bool:
        price = float(row["close"])
        ind_val = self._get_value(row, cond["indicator"])
        return _compare(price, cond["operator"], ind_val)

    @staticmethod
    def _check_cross(cond: dict, df: pd.DataFrame) -> bool:
        lookback = int(cond.get("lookback", 3))
        window = df.iloc[-lookback - 1:]
        fast = window[cond["fast"]].values
        slow = window[cond["slow"]].values
        direction = cond["direction"]  # "above" | "below"

        for i in range(1, len(fast)):
            if direction == "above" and fast[i - 1] <= slow[i - 1] and fast[i] > slow[i]:
                return True
            if direction == "below" and fast[i - 1] >= slow[i - 1] and fast[i] < slow[i]:
                return True
        return False

    @staticmethod
    def _check_volume_spike(cond: dict, row: pd.Series) -> bool:
        multiplier = float(cond.get("multiplier", 1.5))
        vol = row.get("volume")
        vol_sma = row.get("volume_sma_20")
        if pd.isna(vol) or pd.isna(vol_sma) or vol_sma == 0:
            return False
        return float(vol) >= multiplier * float(vol_sma)

    @staticmethod
    def _check_breakout(cond: dict, df: pd.DataFrame) -> bool:
        period = int(cond.get("period", 20))
        direction = cond["direction"]  # "above" | "below"
        window = df.iloc[-period - 1:-1]  # prior bars, excluding current
        current_close = float(df["close"].iloc[-1])

        if direction == "above":
            level = float(window["high"].max())
            return current_close > level
        else:
            level = float(window["low"].min())
            return current_close < level

    # ── Signal construction ───────────────────────────────────────────────────

    @staticmethod
    def _build_signal(
        rule: dict, ticker: str, timeframe: str, df: pd.DataFrame
    ) -> Signal:
        row = df.iloc[-1]
        rsi_val = row.get("rsi_14")
        return Signal(
            ticker=ticker,
            timeframe=timeframe,
            rule_name=rule["name"],
            signal=rule["signal"],
            confidence=float(rule.get("confidence", 0.5)),
            price=float(row["close"]),
            rsi=float(rsi_val) if rsi_val and not pd.isna(rsi_val) else None,
            description=rule.get("description", ""),
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _compare(a: float, op: str, b: float) -> bool:
    ops: dict[str, Any] = {
        "<":  lambda x, y: x < y,
        "<=": lambda x, y: x <= y,
        ">":  lambda x, y: x > y,
        ">=": lambda x, y: x >= y,
        "==": lambda x, y: x == y,
        "!=": lambda x, y: x != y,
    }
    fn = ops.get(op)
    if fn is None:
        raise ValueError(f"Unknown operator: {op}")
    return fn(a, b)

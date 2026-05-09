"""
Inbox processor for TradingView webhook events.

Reads agent_packet JSON files from signals/inbox/, converts them into
MTFSignal objects compatible with the trading agent loop, and moves
processed files to signals/inbox/processed/.

Signal routing by confluence level:
  HIGH   → execute (paper/live order placement)
  MEDIUM → alert only (Discord/log)
  LOW    → alert only (Discord/log)
"""

import json
import logging
import shutil
from dataclasses import field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from analysis.mtf_scanner import MTFSignal
from analysis.scanner import Signal

logger = logging.getLogger(__name__)

DEFAULT_INBOX_DIR = "signals/inbox"
DEFAULT_PROCESSED_DIR = "signals/inbox/processed"

# Confluence → confidence score mapping
CONFLUENCE_CONFIDENCE = {
    "HIGH": 0.85,
    "MEDIUM": 0.65,
    "LOW": 0.45,
}

# Default routing: confluence level → action
DEFAULT_ROUTING = {
    "HIGH": "execute",
    "MEDIUM": "alert",
    "LOW": "alert",
}


class InboxSignal:
    """
    A signal derived from a TradingView webhook event.

    Wraps the agent_packet data and provides conversion to MTFSignal
    for compatibility with the existing agent loop.
    """

    def __init__(self, agent_packet: dict, file_path: Optional[Path] = None):
        self.packet = agent_packet
        self.file_path = file_path

    @property
    def symbol(self) -> str:
        return self.packet.get("symbol", "")

    @property
    def confluence(self) -> str:
        return self.packet.get("confluence", "LOW")

    @property
    def bias(self) -> str:
        return self.packet.get("bias", "NEUTRAL")

    @property
    def event_id(self) -> str:
        return self.packet.get("event_id", "")

    @property
    def action(self) -> str:
        """What to do with this signal based on routing config."""
        return self._routing.get(self.confluence, "alert")

    def set_routing(self, routing: dict) -> None:
        self._routing = routing

    _routing: dict = DEFAULT_ROUTING

    def to_mtf_signal(self) -> MTFSignal:
        """Convert agent_packet into an MTFSignal for the agent loop."""
        packet = self.packet
        pattern = packet.get("pattern", {})
        momentum = packet.get("momentum", {})
        levels = packet.get("levels", {})

        # Determine direction
        bias = packet.get("bias", "NEUTRAL").upper()
        signal_dir = "buy" if bias == "BULLISH" else "sell" if bias == "BEARISH" else "buy"

        # Map confluence to confidence
        confluence = packet.get("confluence", "LOW").upper()
        confidence = CONFLUENCE_CONFIDENCE.get(confluence, 0.45)

        # Build description
        manual_type = pattern.get("manual_type", "unknown")
        stage = packet.get("stage", "")
        score = packet.get("score", 0)
        reasons = packet.get("reasons", [])

        desc_parts = [
            f"[TV WEBHOOK] {manual_type}",
            f"stage={stage}",
            f"score={score}",
            f"confluence={confluence}",
        ]
        if reasons:
            desc_parts.append(f"reasons={','.join(reasons[:3])}")
        description = " | ".join(desc_parts)

        # Build rule name from pattern
        rule_name = f"tv_webhook_{manual_type}"

        # Get timeframe (TV sends as minutes string, e.g. "60")
        tf_raw = packet.get("timeframe", "")
        timeframe = self._normalize_timeframe(tf_raw)

        # Price from levels or 0
        price = levels.get("entry") or 0.0

        # RSI from momentum
        rsi = momentum.get("rsi")

        return MTFSignal(
            ticker=self._normalize_symbol(packet.get("symbol", "")),
            rule_name=rule_name,
            signal=signal_dir,
            base_confidence=confidence,
            mtf_confidence=confidence,
            majority_ratio=1.0,  # single-source signal
            timeframes_triggered=[timeframe],
            timeframes_checked=[timeframe],
            prices={timeframe: price} if price else {},
            rsi_values={timeframe: rsi} if rsi else {},
            description=description,
            profile="tv_webhook",
            timestamp=packet.get("received_at", datetime.now(timezone.utc).isoformat()),
        )

    @staticmethod
    def _normalize_timeframe(tf: str) -> str:
        """Convert TradingView timeframe format to agent format."""
        tf = str(tf).strip()
        # TradingView sends minutes as plain numbers
        try:
            minutes = int(tf)
            if minutes < 60:
                return f"{minutes}m"
            elif minutes == 60:
                return "1h"
            elif minutes == 240:
                return "4h"
            elif minutes == 720:
                return "12h"
            elif minutes == 1440:
                return "1d"
            elif minutes == 10080:
                return "1wk"
            else:
                return f"{minutes}m"
        except ValueError:
            # Already formatted (e.g., "1h", "4h", "1d")
            return tf

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """
        Normalize TV symbol to agent format.
        e.g. BTCUSDT → BTC/USD, XAUUSD stays XAUUSD
        """
        s = symbol.upper()
        # Common crypto pairs: strip trailing T (Binance convention)
        crypto_bases = ["BTC", "ETH", "XRP", "SOL", "DOGE", "HBAR", "SUI", "ADA", "AVAX"]
        for base in crypto_bases:
            if s == f"{base}USDT" or s == f"{base}USD":
                return f"{base}/USD"
        return s


class InboxProcessor:
    """
    Processes agent_packet files from the signals inbox.

    Reads JSON files, converts to signals, and moves processed files
    to the processed subdirectory.
    """

    def __init__(
        self,
        inbox_dir: str = DEFAULT_INBOX_DIR,
        processed_dir: str = DEFAULT_PROCESSED_DIR,
        signal_routing: Optional[dict] = None,
    ):
        self._inbox_dir = Path(inbox_dir)
        self._processed_dir = Path(processed_dir)
        self._routing = signal_routing or DEFAULT_ROUTING

        self._inbox_dir.mkdir(parents=True, exist_ok=True)
        self._processed_dir.mkdir(parents=True, exist_ok=True)

    def process(self) -> list[InboxSignal]:
        """
        Read all pending inbox files, convert to InboxSignals.

        Moves processed files to processed/ directory.
        Returns list of InboxSignal objects ready for the agent loop.
        """
        json_files = sorted(self._inbox_dir.glob("*.json"))
        if not json_files:
            return []

        signals = []
        for path in json_files:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Skipping invalid inbox file %s: %s", path.name, exc)
                self._move_to_processed(path)
                continue

            # Skip if not accepted by webhook validation
            if not data.get("accepted", True):
                logger.info(
                    "Skipping rejected event %s (%s)",
                    data.get("event_id", "?"),
                    data.get("missing_fields", []),
                )
                self._move_to_processed(path)
                continue

            inbox_signal = InboxSignal(data, file_path=path)
            inbox_signal.set_routing(self._routing)
            signals.append(inbox_signal)

            logger.info(
                "Inbox event: %s %s %s conf=%s action=%s",
                data.get("event_id", "?"),
                data.get("symbol", "?"),
                data.get("bias", "?"),
                data.get("confluence", "?"),
                inbox_signal.action,
            )

            # Move to processed
            self._move_to_processed(path)

        if signals:
            logger.info("Processed %d inbox events", len(signals))
        return signals

    def pending_count(self) -> int:
        """Count of unprocessed inbox files."""
        return len(list(self._inbox_dir.glob("*.json")))

    def _move_to_processed(self, path: Path) -> None:
        """Move a file to the processed directory."""
        try:
            dest = self._processed_dir / path.name
            shutil.move(str(path), str(dest))
        except Exception as exc:
            logger.warning("Could not move %s to processed: %s", path.name, exc)

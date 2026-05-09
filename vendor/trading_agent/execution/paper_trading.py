"""
Paper trading engine.

Simulates order execution, tracks open positions, computes P&L,
and records a complete trade log to data/paper_trades.json.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from analysis.scanner import Signal

logger = logging.getLogger(__name__)

_DATA_FILE = "data/paper_trades.json"


class Position:
    def __init__(
        self,
        ticker: str,
        direction: str,
        entry_price: float,
        quantity: float,
        stop_loss: float,
        take_profit: float,
        rule_name: str,
        opened_at: str,
    ):
        self.ticker = ticker
        self.direction = direction          # "long" | "short"
        self.entry_price = entry_price
        self.quantity = quantity
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.rule_name = rule_name
        self.opened_at = opened_at
        self.closed_at: Optional[str] = None
        self.exit_price: Optional[float] = None
        self.pnl: Optional[float] = None

    def current_pnl(self, current_price: float) -> float:
        if self.direction == "long":
            return (current_price - self.entry_price) * self.quantity
        return (self.entry_price - current_price) * self.quantity

    def should_stop(self, current_price: float) -> bool:
        if self.direction == "long":
            return current_price <= self.stop_loss
        return current_price >= self.stop_loss

    def should_take_profit(self, current_price: float) -> bool:
        if self.direction == "long":
            return current_price >= self.take_profit
        return current_price <= self.take_profit

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "quantity": self.quantity,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "rule_name": self.rule_name,
            "opened_at": self.opened_at,
            "closed_at": self.closed_at,
            "exit_price": self.exit_price,
            "pnl": self.pnl,
        }


class PaperTrader:

    def __init__(
        self,
        balance: float = 100_000.0,
        max_position_pct: float = 0.05,
        stop_loss_pct: float = 0.02,
        take_profit_pct: float = 0.04,
        data_file: str = _DATA_FILE,
    ):
        self.balance = balance
        self.initial_balance = balance
        self.max_position_pct = max_position_pct
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.data_file = data_file
        self.open_positions: list[Position] = []
        self.closed_trades: list[dict] = []
        self._load()

    # ── Public ────────────────────────────────────────────────────────────────

    def process_signal(self, signal: Signal) -> Optional[Position]:
        """
        Open a new paper position for a signal (if not already holding this ticker).
        Returns the Position if opened, None otherwise.
        """
        # Don't double up on the same ticker
        if any(p.ticker == signal.ticker for p in self.open_positions):
            logger.debug("Already holding %s – skipping new signal", signal.ticker)
            return None

        price = signal.price
        position_value = self.balance * self.max_position_pct
        quantity = position_value / price

        if signal.signal == "buy":
            direction = "long"
            stop_loss = price * (1 - self.stop_loss_pct)
            take_profit = price * (1 + self.take_profit_pct)
        else:
            direction = "short"
            stop_loss = price * (1 + self.stop_loss_pct)
            take_profit = price * (1 - self.take_profit_pct)

        pos = Position(
            ticker=signal.ticker,
            direction=direction,
            entry_price=price,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            rule_name=signal.rule_name,
            opened_at=datetime.now(timezone.utc).isoformat(),
        )
        self.open_positions.append(pos)
        self.balance -= position_value

        logger.info(
            "PAPER OPEN  %s %s @ $%.4g  SL=$%.4g  TP=$%.4g  (qty=%.4f)",
            direction.upper(), signal.ticker, price, stop_loss, take_profit, quantity,
        )
        self._save()
        return pos

    def update_positions(self, ticker_prices: dict[str, float]) -> list[dict]:
        """
        Check open positions against latest prices and close any that hit SL/TP.
        Returns list of closed trade dicts.
        """
        closed_now = []
        remaining = []

        for pos in self.open_positions:
            price = ticker_prices.get(pos.ticker)
            if price is None:
                remaining.append(pos)
                continue

            reason = None
            if pos.should_stop(price):
                reason = "stop_loss"
            elif pos.should_take_profit(price):
                reason = "take_profit"

            if reason:
                closed_trade = self._close_position(pos, price, reason)
                closed_now.append(closed_trade)
            else:
                remaining.append(pos)

        self.open_positions = remaining
        if closed_now:
            self._save()
        return closed_now

    def print_report(self) -> None:
        sep = "─" * 60
        print(f"\n{sep}")
        print("  PAPER TRADING REPORT")
        print(sep)
        print(f"  Initial balance : ${self.initial_balance:,.2f}")
        print(f"  Current balance : ${self.balance:,.2f}")

        unrealized = sum(
            p.current_pnl(p.entry_price) for p in self.open_positions
        )
        total_equity = self.balance + unrealized
        pnl = total_equity - self.initial_balance
        print(f"  Equity          : ${total_equity:,.2f}  ({pnl:+,.2f})")
        print(f"  Open positions  : {len(self.open_positions)}")
        print(f"  Closed trades   : {len(self.closed_trades)}")

        if self.closed_trades:
            wins = [t for t in self.closed_trades if (t.get("pnl") or 0) > 0]
            wr = len(wins) / len(self.closed_trades) if self.closed_trades else 0
            avg_pnl = sum(t.get("pnl", 0) for t in self.closed_trades) / len(self.closed_trades)
            print(f"  Win rate        : {wr:.1%}")
            print(f"  Avg P&L/trade   : ${avg_pnl:+,.2f}")

        print()
        if self.open_positions:
            print("  OPEN POSITIONS")
            for p in self.open_positions:
                print(f"    {p.direction.upper()} {p.ticker}  entry=${p.entry_price:.4g}  "
                      f"SL=${p.stop_loss:.4g}  TP=${p.take_profit:.4g}")
        print(sep)

    # ── Class method for loading from disk ───────────────────────────────────

    @classmethod
    def load(cls, data_file: str = _DATA_FILE) -> "PaperTrader":
        trader = cls(data_file=data_file)
        return trader

    # ── Private ───────────────────────────────────────────────────────────────

    def _close_position(self, pos: Position, exit_price: float, reason: str) -> dict:
        pos.exit_price = exit_price
        pos.closed_at = datetime.now(timezone.utc).isoformat()
        pos.pnl = pos.current_pnl(exit_price)
        self.balance += pos.entry_price * pos.quantity + pos.pnl

        trade_dict = pos.to_dict()
        trade_dict["close_reason"] = reason
        self.closed_trades.append(trade_dict)

        outcome = "WIN" if pos.pnl > 0 else "LOSS"
        logger.info(
            "PAPER CLOSE %s %s @ $%.4g  P&L=$%.2f  (%s via %s)",
            pos.direction.upper(), pos.ticker, exit_price, pos.pnl, outcome, reason,
        )
        return trade_dict

    def _save(self) -> None:
        Path(self.data_file).parent.mkdir(parents=True, exist_ok=True)
        state = {
            "balance": self.balance,
            "initial_balance": self.initial_balance,
            "open_positions": [p.to_dict() for p in self.open_positions],
            "closed_trades": self.closed_trades,
        }
        Path(self.data_file).write_text(json.dumps(state, indent=2))

    def _load(self) -> None:
        path = Path(self.data_file)
        if not path.exists():
            return
        try:
            state = json.loads(path.read_text())
            self.balance = state.get("balance", self.balance)
            self.initial_balance = state.get("initial_balance", self.initial_balance)
            self.closed_trades = state.get("closed_trades", [])
            # Open positions are not restored across restarts to avoid stale data
        except Exception as exc:
            logger.warning("Could not restore paper trader state: %s", exc)

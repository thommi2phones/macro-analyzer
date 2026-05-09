"""
Alpaca broker — live and paper order execution.

Wraps alpaca-py's TradingClient to provide a clean, unified interface
for placing orders, managing positions, and querying account state.

Paper trading is controlled by the `paper` flag (default True).
Set ALPACA_PAPER=false in .env to switch to live trading.
"""

import logging
import os
from dataclasses import dataclass
from typing import Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, OrderType, TimeInForce
from alpaca.trading.requests import (
    LimitOrderRequest,
    MarketOrderRequest,
    TakeProfitRequest,
    StopLossRequest,
)

from analysis.scanner import Signal

logger = logging.getLogger(__name__)


@dataclass
class OrderResult:
    order_id: str
    ticker: str
    side: str
    qty: float
    order_type: str
    status: str
    submitted_at: str


@dataclass
class Position:
    ticker: str
    qty: float
    side: str             # "long" | "short"
    avg_entry: float
    current_price: float
    unrealized_pnl: float
    unrealized_pnl_pct: float


class AlpacaBroker:

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        paper: bool = True,
    ):
        key    = api_key    or os.getenv("ALPACA_API_KEY", "")
        secret = secret_key or os.getenv("ALPACA_SECRET_KEY", "")

        if not key or not secret:
            raise ValueError(
                "ALPACA_API_KEY and ALPACA_SECRET_KEY must be set in .env "
                "to use AlpacaBroker."
            )

        self._client = TradingClient(key, secret, paper=paper)
        self._paper  = paper
        mode = "PAPER" if paper else "LIVE"
        logger.info("AlpacaBroker initialized in %s mode", mode)

    # ── Account ───────────────────────────────────────────────────────────────

    def get_account(self) -> dict:
        acc = self._client.get_account()
        return {
            "cash":            float(acc.cash),
            "equity":          float(acc.equity),
            "buying_power":    float(acc.buying_power),
            "portfolio_value": float(acc.portfolio_value),
            "daytrade_count":  int(acc.daytrade_count),
            "pattern_day_trader": acc.pattern_day_trader,
        }

    def print_account_summary(self) -> None:
        acc = self.get_account()
        print(
            f"\n{'─'*40}\n"
            f"  {'PAPER' if self._paper else 'LIVE'} ACCOUNT\n"
            f"  Portfolio : ${acc['portfolio_value']:,.2f}\n"
            f"  Cash      : ${acc['cash']:,.2f}\n"
            f"  Buying Pwr: ${acc['buying_power']:,.2f}\n"
            f"{'─'*40}\n"
        )

    # ── Positions ─────────────────────────────────────────────────────────────

    def get_positions(self) -> list[Position]:
        raw = self._client.get_all_positions()
        return [
            Position(
                ticker=p.symbol,
                qty=float(p.qty),
                side="long" if float(p.qty) > 0 else "short",
                avg_entry=float(p.avg_entry_price),
                current_price=float(p.current_price),
                unrealized_pnl=float(p.unrealized_pl),
                unrealized_pnl_pct=float(p.unrealized_plpc) * 100,
            )
            for p in raw
        ]

    def get_position(self, ticker: str) -> Optional[Position]:
        positions = self.get_positions()
        return next((p for p in positions if p.ticker == ticker), None)

    def close_position(self, ticker: str) -> bool:
        try:
            self._client.close_position(ticker)
            logger.info("Closed position: %s", ticker)
            return True
        except Exception as exc:
            logger.error("Failed to close position %s: %s", ticker, exc)
            return False

    def close_all_positions(self) -> None:
        self._client.close_all_positions(cancel_orders=True)
        logger.info("All positions closed")

    # ── Orders ────────────────────────────────────────────────────────────────

    def market_order(
        self,
        ticker: str,
        side: str,
        qty: float,
        stop_loss_price: Optional[float] = None,
        take_profit_price: Optional[float] = None,
        time_in_force: TimeInForce = TimeInForce.DAY,
    ) -> Optional[OrderResult]:
        """
        Place a market order, optionally with bracket (SL + TP).
        """
        alpaca_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL

        # Bracket order if SL/TP provided
        if stop_loss_price or take_profit_price:
            return self._bracket_order(
                ticker, alpaca_side, qty,
                stop_loss_price, take_profit_price, time_in_force,
            )

        req = MarketOrderRequest(
            symbol=ticker,
            qty=qty,
            side=alpaca_side,
            time_in_force=time_in_force,
        )
        return self._submit(req)

    def limit_order(
        self,
        ticker: str,
        side: str,
        qty: float,
        limit_price: float,
        stop_loss_price: Optional[float] = None,
        take_profit_price: Optional[float] = None,
        time_in_force: TimeInForce = TimeInForce.GTC,
    ) -> Optional[OrderResult]:
        alpaca_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL

        if stop_loss_price or take_profit_price:
            return self._bracket_order(
                ticker, alpaca_side, qty,
                stop_loss_price, take_profit_price, time_in_force,
                limit_price=limit_price,
            )

        req = LimitOrderRequest(
            symbol=ticker,
            qty=qty,
            side=alpaca_side,
            time_in_force=time_in_force,
            limit_price=limit_price,
        )
        return self._submit(req)

    def order_from_signal(
        self,
        signal: Signal,
        qty: float,
        stop_loss_pct: float = 0.02,
        take_profit_pct: float = 0.04,
    ) -> Optional[OrderResult]:
        """
        Convenience: place a market order from a Signal with automatic SL/TP.
        """
        side = "buy" if signal.signal == "buy" else "sell"
        price = signal.price

        if side == "buy":
            sl = round(price * (1 - stop_loss_pct), 4)
            tp = round(price * (1 + take_profit_pct), 4)
        else:
            sl = round(price * (1 + stop_loss_pct), 4)
            tp = round(price * (1 - take_profit_pct), 4)

        return self.market_order(
            ticker=signal.ticker,
            side=side,
            qty=qty,
            stop_loss_price=sl,
            take_profit_price=tp,
        )

    # ── Private ───────────────────────────────────────────────────────────────

    def _bracket_order(
        self,
        ticker: str,
        side: OrderSide,
        qty: float,
        stop_loss_price: Optional[float],
        take_profit_price: Optional[float],
        time_in_force: TimeInForce,
        limit_price: Optional[float] = None,
    ) -> Optional[OrderResult]:
        from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest

        kwargs = dict(
            symbol=ticker,
            qty=qty,
            side=side,
            time_in_force=time_in_force,
        )
        if take_profit_price:
            kwargs["take_profit"] = TakeProfitRequest(limit_price=take_profit_price)
        if stop_loss_price:
            kwargs["stop_loss"] = StopLossRequest(stop_price=stop_loss_price)

        if limit_price:
            kwargs["limit_price"] = limit_price
            req = LimitOrderRequest(**kwargs)
        else:
            req = MarketOrderRequest(**kwargs)

        return self._submit(req)

    def _submit(self, req) -> Optional[OrderResult]:
        try:
            order = self._client.submit_order(req)
            result = OrderResult(
                order_id=str(order.id),
                ticker=order.symbol,
                side=str(order.side.value),
                qty=float(order.qty or 0),
                order_type=str(order.type.value),
                status=str(order.status.value),
                submitted_at=str(order.submitted_at),
            )
            logger.info(
                "Order submitted: %s %s %s  id=%s",
                result.side.upper(), result.qty, result.ticker, result.order_id,
            )
            return result
        except Exception as exc:
            logger.error("Order submission failed: %s", exc)
            return None

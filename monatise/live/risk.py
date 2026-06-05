from __future__ import annotations

from dataclasses import dataclass

from monatise.core.models import Order, OrderSide, Portfolio
from monatise.live.config import RuntimeConfig


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str = ""


class RiskManager:
    def __init__(self, config: RuntimeConfig, starting_equity: float) -> None:
        self.config = config
        self.starting_equity = starting_equity
        self.kill_switch = False

    def stop(self) -> None:
        self.kill_switch = True

    def resume(self) -> None:
        self.kill_switch = False

    def check_batch(self, orders: list[Order], portfolio: Portfolio, mark_price: float) -> RiskDecision:
        if self.kill_switch:
            return RiskDecision(False, "kill switch is active")

        equity = portfolio.equity(mark_price)
        if self.starting_equity - equity > self.config.max_daily_loss:
            self.kill_switch = True
            return RiskDecision(False, "max daily loss reached")

        total_notional = sum(order.notional for order in orders)
        if total_notional > self.config.max_total_notional + 1e-9:
            return RiskDecision(False, "batch notional exceeds risk limit")

        for order in orders:
            decision = self.check_order(order, portfolio)
            if not decision.allowed:
                return decision
        return RiskDecision(True)

    def check_order(self, order: Order, portfolio: Portfolio) -> RiskDecision:
        if order.notional > self.config.max_order_notional + 1e-9:
            return RiskDecision(False, f"order {order.order_id} exceeds max notional")
        if order.side is OrderSide.BUY and portfolio.base >= self.config.max_base_inventory:
            return RiskDecision(False, "base inventory cap reached")
        return RiskDecision(True)

from __future__ import annotations

from dataclasses import dataclass

from monatise.core.models import Order, OrderSide, Portfolio
from monatise.live.config import RuntimeConfig


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str = ""


@dataclass(frozen=True)
class RiskSnapshot:
    starting_equity: float
    equity: float
    drawdown: float
    drawdown_pct: float
    kill_switch: bool
    open_order_notional: float
    max_total_notional: float
    max_daily_loss: float


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

    def snapshot(self, orders: list[Order], portfolio: Portfolio, mark_price: float) -> RiskSnapshot:
        equity = portfolio.equity(mark_price)
        drawdown = max(0.0, self.starting_equity - equity)
        drawdown_pct = 0.0 if self.starting_equity <= 0 else drawdown / self.starting_equity
        return RiskSnapshot(
            starting_equity=self.starting_equity,
            equity=equity,
            drawdown=drawdown,
            drawdown_pct=drawdown_pct,
            kill_switch=self.kill_switch,
            open_order_notional=sum(order.notional for order in orders),
            max_total_notional=self.config.max_total_notional,
            max_daily_loss=self.config.max_daily_loss,
        )

    def check_order(self, order: Order, portfolio: Portfolio) -> RiskDecision:
        if order.notional > self.config.max_order_notional + 1e-9:
            return RiskDecision(False, f"order {order.order_id} exceeds max notional")
        if order.side is OrderSide.BUY and portfolio.base >= self.config.max_base_inventory:
            return RiskDecision(False, "base inventory cap reached")
        return RiskDecision(True)

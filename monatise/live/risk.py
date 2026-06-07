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
    leverage: float
    open_order_notional: float
    estimated_margin_used: float
    max_total_notional: float
    max_grid_margin: float
    max_daily_loss: float
    max_daily_loss_pct: float


class RiskManager:
    def __init__(self, config: RuntimeConfig, starting_equity: float) -> None:
        self.config = config
        self.starting_equity = starting_equity
        self.kill_switch = False

    def stop(self) -> None:
        self.kill_switch = True

    def resume(self) -> None:
        self.kill_switch = False

    def daily_loss_limit(self) -> float:
        if self.config.max_daily_loss_pct is not None:
            return self.starting_equity * self.config.max_daily_loss_pct
        return self.config.max_daily_loss

    def check_batch(self, orders: list[Order], portfolio: Portfolio, mark_price: float) -> RiskDecision:
        if self.kill_switch:
            return RiskDecision(False, "kill switch is active")

        equity = portfolio.equity(mark_price)
        if self.starting_equity - equity > self.daily_loss_limit():
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
        open_order_notional = sum(order.notional for order in orders)
        leverage = max(self.config.leverage, 1e-9)
        return RiskSnapshot(
            starting_equity=self.starting_equity,
            equity=equity,
            drawdown=drawdown,
            drawdown_pct=drawdown_pct,
            kill_switch=self.kill_switch,
            leverage=self.config.leverage,
            open_order_notional=open_order_notional,
            estimated_margin_used=open_order_notional / leverage,
            max_total_notional=self.config.max_total_notional,
            max_grid_margin=self.config.max_total_notional / leverage,
            max_daily_loss=self.daily_loss_limit(),
            max_daily_loss_pct=0.0 if self.starting_equity <= 0 else self.daily_loss_limit() / self.starting_equity,
        )

    def check_order(self, order: Order, portfolio: Portfolio) -> RiskDecision:
        if order.notional > self.config.max_order_notional + 1e-9:
            return RiskDecision(False, f"order {order.order_id} exceeds max notional")
        if order.side is OrderSide.BUY and portfolio.base >= self.config.max_base_inventory:
            return RiskDecision(False, "base inventory cap reached")
        return RiskDecision(True)

from __future__ import annotations

from dataclasses import dataclass
from math import floor

from monatise.core.models import Fill, Order, OrderSide, Portfolio
from monatise.strategy.grid import Grid, GridConfig


@dataclass(frozen=True)
class LiquidityHarvesterConfig:
    symbol: str
    center_price: float
    spacing_pct: float = 0.005
    levels_each_side: int = 5
    order_quote_size: float = 100.0
    fee_rate: float = 0.0004
    target_inventory_ratio: float = 0.5
    max_inventory_skew: float = 0.25

    def validate(self) -> None:
        if not self.symbol:
            raise ValueError("symbol is required")
        GridConfig(self.center_price, self.spacing_pct, self.levels_each_side).validate()
        if self.order_quote_size <= 0:
            raise ValueError("order_quote_size must be positive")
        if self.fee_rate < 0:
            raise ValueError("fee_rate cannot be negative")
        if not 0 <= self.target_inventory_ratio <= 1:
            raise ValueError("target_inventory_ratio must be between 0 and 1")
        if not 0 <= self.max_inventory_skew <= 1:
            raise ValueError("max_inventory_skew must be between 0 and 1")


class LiquidityHarvester:
    """Plans grid liquidity and records harvest cycles.

    This class is exchange-agnostic. API adapters can call `plan_orders`, submit
    the orders externally, then feed fills back through `record_fill`.
    """

    def __init__(self, config: LiquidityHarvesterConfig) -> None:
        config.validate()
        self.config = config
        self._matched_buys: dict[str, Fill] = {}

    def plan_orders(self, portfolio: Portfolio, mark_price: float | None = None) -> list[Order]:
        mark = mark_price or self.config.center_price
        inventory_ratio = portfolio.inventory_ratio(mark)
        buy_allowed = inventory_ratio <= self.config.target_inventory_ratio + self.config.max_inventory_skew
        sell_allowed = inventory_ratio >= self.config.target_inventory_ratio - self.config.max_inventory_skew

        orders: list[Order] = []
        available_quote = portfolio.quote
        available_base = portfolio.base
        for level in Grid(self._grid_config(mark)).levels():
            if level.side is OrderSide.BUY and not buy_allowed:
                continue
            if level.side is OrderSide.SELL and not sell_allowed:
                continue

            quantity = floor((self.config.order_quote_size / level.price) * 1e10) / 1e10
            order = Order(
                symbol=self.config.symbol,
                side=level.side,
                price=level.price,
                quantity=round(quantity, 10),
                level_id=level.level_id,
                metadata={"mark_price": mark, "inventory_ratio": inventory_ratio},
            )
            fee = order.notional * self.config.fee_rate
            if order.side is OrderSide.BUY and order.notional + fee <= available_quote + 1e-8:
                orders.append(order)
                available_quote = max(0.0, available_quote - order.notional - fee)
            elif order.side is OrderSide.SELL and order.quantity <= available_base + 1e-10:
                orders.append(order)
                available_base = max(0.0, available_base - order.quantity)
        return orders

    def record_fill(self, fill: Fill, portfolio: Portfolio) -> None:
        portfolio.apply_fill(fill)
        if fill.side is OrderSide.BUY:
            self._matched_buys[fill.level_id] = fill
            return

        paired_level = fill.level_id.replace("sell", "buy", 1)
        buy_fill = self._matched_buys.pop(paired_level, None)
        if buy_fill is None:
            return

        matched_qty = min(buy_fill.quantity, fill.quantity)
        gross = (fill.price - buy_fill.price) * matched_qty
        paired_fees = buy_fill.fee + fill.fee
        portfolio.realized_harvest += gross - paired_fees

    def _grid_config(self, mark_price: float) -> GridConfig:
        return GridConfig(
            center_price=mark_price,
            spacing_pct=self.config.spacing_pct,
            levels_each_side=self.config.levels_each_side,
        )

from __future__ import annotations

from dataclasses import dataclass, field

from monatise.core.models import Candle, Fill, Order, OrderSide, OrderStatus, Portfolio
from monatise.strategy.harvester import LiquidityHarvester


@dataclass(frozen=True)
class SimulationSnapshot:
    timestamp: str
    close: float
    quote: float
    base: float
    equity: float
    realized_harvest: float
    fee_paid: float
    fills: int


@dataclass
class SimulationResult:
    snapshots: list[SimulationSnapshot] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)
    final_portfolio: Portfolio | None = None

    @property
    def final_equity(self) -> float:
        if not self.snapshots:
            return 0.0
        return self.snapshots[-1].equity


class BacktestEngine:
    def __init__(self, harvester: LiquidityHarvester, portfolio: Portfolio) -> None:
        self.harvester = harvester
        self.portfolio = portfolio
        self.open_orders: list[Order] = []

    def run(self, candles: list[Candle]) -> SimulationResult:
        result = SimulationResult()
        if not candles:
            result.final_portfolio = self.portfolio
            return result

        self.open_orders = self.harvester.plan_orders(self.portfolio, candles[0].open)
        for candle in candles:
            fills = self._match_candle(candle)
            for fill in fills:
                self.harvester.record_fill(fill, self.portfolio)
                result.fills.append(fill)

            self.open_orders = self.harvester.plan_orders(self.portfolio, candle.close)
            result.snapshots.append(
                SimulationSnapshot(
                    timestamp=candle.timestamp,
                    close=candle.close,
                    quote=round(self.portfolio.quote, 8),
                    base=round(self.portfolio.base, 10),
                    equity=round(self.portfolio.equity(candle.close), 8),
                    realized_harvest=round(self.portfolio.realized_harvest, 8),
                    fee_paid=round(self.portfolio.fee_paid, 8),
                    fills=len(result.fills),
                )
            )

        result.final_portfolio = self.portfolio
        return result

    def _match_candle(self, candle: Candle) -> list[Fill]:
        fills: list[Fill] = []
        remaining: list[Order] = []

        for order in self.open_orders:
            traded = self._crossed(order, candle)
            if not traded:
                remaining.append(order)
                continue

            fee = order.notional * self.harvester.config.fee_rate
            fill = Fill(
                order_id=order.order_id,
                symbol=order.symbol,
                side=order.side,
                price=order.price,
                quantity=order.quantity,
                fee=round(fee, 10),
                timestamp=candle.timestamp,
                level_id=order.level_id,
            )
            order.status = OrderStatus.FILLED
            fills.append(fill)

        self.open_orders = remaining
        return fills

    def _crossed(self, order: Order, candle: Candle) -> bool:
        if order.side is OrderSide.BUY:
            return candle.low <= order.price
        return candle.high >= order.price

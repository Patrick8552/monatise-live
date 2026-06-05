from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from itertools import count
from typing import Any


_order_ids = count(1)


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(StrEnum):
    OPEN = "open"
    FILLED = "filled"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Candle:
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def validate(self) -> None:
        if self.low > self.high:
            raise ValueError("candle low cannot be greater than high")
        if not (self.low <= self.open <= self.high):
            raise ValueError("candle open must be inside high/low range")
        if not (self.low <= self.close <= self.high):
            raise ValueError("candle close must be inside high/low range")


@dataclass
class Order:
    symbol: str
    side: OrderSide
    price: float
    quantity: float
    level_id: str
    order_id: str = field(default_factory=lambda: f"local-{next(_order_ids)}")
    status: OrderStatus = OrderStatus.OPEN
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def notional(self) -> float:
        return self.price * self.quantity


@dataclass(frozen=True)
class Fill:
    order_id: str
    symbol: str
    side: OrderSide
    price: float
    quantity: float
    fee: float
    timestamp: str
    level_id: str

    @property
    def notional(self) -> float:
        return self.price * self.quantity


@dataclass
class Portfolio:
    quote: float
    base: float = 0.0
    fee_paid: float = 0.0
    realized_harvest: float = 0.0

    def apply_fill(self, fill: Fill) -> None:
        if fill.side is OrderSide.BUY:
            cost = fill.notional + fill.fee
            if cost > self.quote + 1e-9:
                raise ValueError("insufficient quote balance for buy fill")
            self.quote -= cost
            self.base += fill.quantity
        else:
            if fill.quantity > self.base + 1e-9:
                raise ValueError("insufficient base balance for sell fill")
            proceeds = fill.notional - fill.fee
            self.quote += proceeds
            self.base -= fill.quantity
        self.fee_paid += fill.fee

    def equity(self, mark_price: float) -> float:
        return self.quote + (self.base * mark_price)

    def inventory_ratio(self, mark_price: float) -> float:
        total = self.equity(mark_price)
        if total <= 0:
            return 0.0
        return (self.base * mark_price) / total

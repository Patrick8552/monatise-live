from __future__ import annotations

from typing import Protocol

from monatise.core.models import Candle, Fill, Order


class MarketDataPort(Protocol):
    """Future API adapters expose market data through this shape."""

    def latest_price(self, symbol: str) -> float:
        raise NotImplementedError

    def candles(self, symbol: str, limit: int) -> list[Candle]:
        raise NotImplementedError


class ExecutionPort(Protocol):
    """Future exchange adapters expose execution through this shape."""

    def place_orders(self, orders: list[Order]) -> list[Order]:
        raise NotImplementedError

    def cancel_orders(self, order_ids: list[str]) -> None:
        raise NotImplementedError

    def fills(self, symbol: str) -> list[Fill]:
        raise NotImplementedError

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from monatise.engines.market_data.models import MarketSnapshot


class PriceActionFamily(StrEnum):
    CANDLESTICK = "candlestick"
    HEAD_AND_SHOULDERS = "head_and_shoulders"
    ORDER_BLOCK = "order_block"
    WYCKOFF = "wyckoff"


class PriceActionDirection(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"


@dataclass(frozen=True)
class PriceActionSignal:
    family: PriceActionFamily
    pattern: str
    direction: PriceActionDirection
    confidence: float
    confirmed: bool
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PriceActionRequest:
    market: MarketSnapshot
    minimum_candles: int = 8

    def validate(self) -> None:
        if self.minimum_candles < 5:
            raise ValueError("minimum_candles must be at least 5")


@dataclass(frozen=True)
class PriceActionAssessment:
    symbol: str
    signals: tuple[PriceActionSignal, ...]
    reasons: tuple[str, ...]
    registered_families: tuple[PriceActionFamily, ...] = tuple(PriceActionFamily)
    entry_confirmation_required: bool = True

    @property
    def confirmed_signals(self) -> tuple[PriceActionSignal, ...]:
        return tuple(signal for signal in self.signals if signal.confirmed)

    @property
    def has_confirmation(self) -> bool:
        return bool(self.confirmed_signals)

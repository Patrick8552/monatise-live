from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from monatise.engines._validation import require_finite

from monatise.core.models import Candle


class DataStatus(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    NO_DATA = "no_data"


@dataclass(frozen=True)
class MarketDataRequest:
    symbol: str
    interval: str = "15m"
    candle_limit: int = 200
    max_age_seconds: int = 120
    preferred_source: str | None = None

    def validate(self) -> None:
        require_finite(max_age_seconds=self.max_age_seconds)
        if not self.symbol.strip():
            raise ValueError("symbol is required")
        if self.candle_limit < 2:
            raise ValueError("candle_limit must be at least 2")
        if self.max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be positive")


@dataclass(frozen=True)
class DataQuality:
    status: DataStatus
    source: str | None
    observed_at: datetime
    latest_candle_at: datetime | None
    age_seconds: float | None
    issues: tuple[str, ...] = ()

    @property
    def usable(self) -> bool:
        return self.status in {DataStatus.READY, DataStatus.DEGRADED}


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    interval: str
    price: float | None
    candles: tuple[Candle, ...]
    quality: DataQuality
    derivatives: dict[str, float | None] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_trade_analysis_ready(self) -> bool:
        return self.quality.status is DataStatus.READY


def utc_now() -> datetime:
    return datetime.now(timezone.utc)

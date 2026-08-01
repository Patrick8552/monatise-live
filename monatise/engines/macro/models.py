from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class MacroBias(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    CONFLICTED = "conflicted"
    UNKNOWN = "unknown"


class MacroRiskState(StrEnum):
    NORMAL = "normal"
    ELEVATED = "elevated"
    EVENT_LOCK = "event_lock"
    DATA_UNAVAILABLE = "data_unavailable"


class MacroEventImpact(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class MacroEvent:
    name: str
    scheduled_at: datetime
    impact: MacroEventImpact
    currency: str | None = None
    country: str | None = None
    actual: float | None = None
    forecast: float | None = None
    previous: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MacroRequest:
    symbol: str
    observed_at: datetime
    event_lock_before_minutes: int = 30
    event_lock_after_minutes: int = 60
    include_currencies: tuple[str, ...] = ("USD",)
    allow_partial_context: bool = True

    def validate(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol is required")
        if self.event_lock_before_minutes < 0:
            raise ValueError("event_lock_before_minutes cannot be negative")
        if self.event_lock_after_minutes < 0:
            raise ValueError("event_lock_after_minutes cannot be negative")


@dataclass(frozen=True)
class MacroAssessment:
    symbol: str
    bias: MacroBias
    risk_state: MacroRiskState
    conviction: float
    score: float
    reasons: tuple[str, ...]
    active_events: tuple[MacroEvent, ...] = ()
    upcoming_events: tuple[MacroEvent, ...] = ()
    factors: dict[str, float | None] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def blocks_new_analysis(self) -> bool:
        return self.risk_state in {
            MacroRiskState.EVENT_LOCK,
            MacroRiskState.DATA_UNAVAILABLE,
        }

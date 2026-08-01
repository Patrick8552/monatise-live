from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from monatise.engines._validation import require_finite


class PortfolioHealth(StrEnum):
    HEALTHY = "healthy"
    ELEVATED = "elevated"
    FRAGILE = "fragile"
    BLOCKED = "blocked"


class PortfolioRiskFlag(StrEnum):
    HIGH_TOTAL_RISK = "high_total_risk"
    SYMBOL_CONCENTRATION = "symbol_concentration"
    CORRELATION_CLUSTER = "correlation_cluster"
    DIRECTIONAL_CROWDING = "directional_crowding"
    LEVERAGE_CONCENTRATION = "leverage_concentration"
    LIQUIDITY_CONCENTRATION = "liquidity_concentration"
    EXPIRY_CLUSTER = "expiry_cluster"
    NONE = "none"


@dataclass(frozen=True)
class PortfolioPosition:
    position_id: str
    symbol: str
    side: str
    notional: float
    risk_amount: float
    leverage: float
    correlation_group: str | None = None
    liquidity_tier: str | None = None
    signal_expires_at_epoch: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        require_finite(
            notional=self.notional,
            risk_amount=self.risk_amount,
            leverage=self.leverage,
        )
        if not self.position_id.strip():
            raise ValueError("position_id is required")
        if not self.symbol.strip():
            raise ValueError("symbol is required")
        if self.side not in {"long", "short", "two_sided"}:
            raise ValueError("side must be long, short, or two_sided")
        if self.notional < 0:
            raise ValueError("notional cannot be negative")
        if self.risk_amount < 0:
            raise ValueError("risk_amount cannot be negative")
        if self.leverage <= 0:
            raise ValueError("leverage must be positive")


@dataclass(frozen=True)
class PortfolioIntelligenceRequest:
    total_equity: float
    positions: tuple[PortfolioPosition, ...]
    maximum_total_risk_pct: float = 0.06
    maximum_symbol_notional_pct: float = 0.20
    maximum_correlation_group_pct: float = 0.35
    maximum_directional_notional_pct: float = 0.60
    maximum_weighted_leverage: float = 3.0
    maximum_low_liquidity_notional_pct: float = 0.20
    expiry_cluster_window_seconds: int = 900

    def validate(self) -> None:
        require_finite(
            total_equity=self.total_equity,
            maximum_total_risk_pct=self.maximum_total_risk_pct,
            maximum_symbol_notional_pct=self.maximum_symbol_notional_pct,
            maximum_correlation_group_pct=self.maximum_correlation_group_pct,
            maximum_directional_notional_pct=self.maximum_directional_notional_pct,
            maximum_low_liquidity_notional_pct=self.maximum_low_liquidity_notional_pct,
            maximum_weighted_leverage=self.maximum_weighted_leverage,
        )
        if self.total_equity <= 0:
            raise ValueError("total_equity must be positive")
        for position in self.positions:
            position.validate()
        for name, value in {
            "maximum_total_risk_pct": self.maximum_total_risk_pct,
            "maximum_symbol_notional_pct": self.maximum_symbol_notional_pct,
            "maximum_correlation_group_pct": self.maximum_correlation_group_pct,
            "maximum_directional_notional_pct": self.maximum_directional_notional_pct,
            "maximum_low_liquidity_notional_pct": self.maximum_low_liquidity_notional_pct,
        }.items():
            if not 0 < value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.maximum_weighted_leverage <= 0:
            raise ValueError("maximum_weighted_leverage must be positive")
        if self.expiry_cluster_window_seconds < 0:
            raise ValueError("expiry_cluster_window_seconds cannot be negative")


@dataclass(frozen=True)
class PortfolioIntelligenceResult:
    health: PortfolioHealth
    portfolio_heat_pct: float
    gross_notional: float
    net_directional_notional: float
    weighted_leverage: float
    largest_symbol_exposure_pct: float
    largest_correlation_group_pct: float
    low_liquidity_exposure_pct: float
    flags: tuple[PortfolioRiskFlag, ...]
    blockers: tuple[str, ...]
    reasons: tuple[str, ...]
    metrics: dict[str, float]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def permits_new_allocation(self) -> bool:
        return self.health in {
            PortfolioHealth.HEALTHY,
            PortfolioHealth.ELEVATED,
        }

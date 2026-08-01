from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from monatise.engines._validation import require_finite

from monatise.engines.decision.models import DecisionClassification
from monatise.engines.risk_validation.models import RiskResult


class AllocationDecision(StrEnum):
    APPROVED = "approved"
    REDUCED = "reduced"
    BLOCKED = "blocked"


class AllocationTier(StrEnum):
    FULL = "full"
    REDUCED = "reduced"
    MINIMAL = "minimal"
    NONE = "none"


class AllocationProfile(StrEnum):
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"
    PAPER_TEST = "paper_test"


@dataclass(frozen=True)
class AllocationProfileConfig:
    maximum_crypto_exposure_pct: float
    maximum_symbol_exposure_pct: float
    maximum_correlated_exposure_pct: float
    maximum_open_risk_pct: float
    maximum_open_positions: int
    maximum_symbol_positions: int
    full_allocation_score: float
    reduced_allocation_score: float
    minimal_allocation_score: float
    full_multiplier: float
    reduced_multiplier: float
    minimal_multiplier: float
    grid_multiplier: float
    live_capable: bool

    def validate(self) -> None:
        percentage_fields = {
            "maximum_crypto_exposure_pct": self.maximum_crypto_exposure_pct,
            "maximum_symbol_exposure_pct": self.maximum_symbol_exposure_pct,
            "maximum_correlated_exposure_pct": self.maximum_correlated_exposure_pct,
            "maximum_open_risk_pct": self.maximum_open_risk_pct,
            "full_allocation_score": self.full_allocation_score,
            "reduced_allocation_score": self.reduced_allocation_score,
            "minimal_allocation_score": self.minimal_allocation_score,
            "full_multiplier": self.full_multiplier,
            "reduced_multiplier": self.reduced_multiplier,
            "minimal_multiplier": self.minimal_multiplier,
            "grid_multiplier": self.grid_multiplier,
        }
        require_finite(**percentage_fields)
        for name, value in percentage_fields.items():
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        if not (
            self.full_allocation_score
            >= self.reduced_allocation_score
            >= self.minimal_allocation_score
        ):
            raise ValueError("allocation score thresholds are out of order")
        if self.maximum_open_positions < 1:
            raise ValueError("maximum_open_positions must be positive")
        if self.maximum_symbol_positions < 1:
            raise ValueError("maximum_symbol_positions must be positive")


PROFILE_CONFIGS: dict[AllocationProfile, AllocationProfileConfig] = {
    AllocationProfile.CONSERVATIVE: AllocationProfileConfig(
        maximum_crypto_exposure_pct=0.25,
        maximum_symbol_exposure_pct=0.07,
        maximum_correlated_exposure_pct=0.15,
        maximum_open_risk_pct=0.025,
        maximum_open_positions=4,
        maximum_symbol_positions=1,
        full_allocation_score=0.82,
        reduced_allocation_score=0.68,
        minimal_allocation_score=0.55,
        full_multiplier=0.70,
        reduced_multiplier=0.45,
        minimal_multiplier=0.20,
        grid_multiplier=0.60,
        live_capable=True,
    ),
    AllocationProfile.BALANCED: AllocationProfileConfig(
        maximum_crypto_exposure_pct=0.50,
        maximum_symbol_exposure_pct=0.15,
        maximum_correlated_exposure_pct=0.30,
        maximum_open_risk_pct=0.06,
        maximum_open_positions=8,
        maximum_symbol_positions=2,
        full_allocation_score=0.75,
        reduced_allocation_score=0.55,
        minimal_allocation_score=0.40,
        full_multiplier=1.00,
        reduced_multiplier=0.60,
        minimal_multiplier=0.30,
        grid_multiplier=0.75,
        live_capable=True,
    ),
    AllocationProfile.AGGRESSIVE: AllocationProfileConfig(
        maximum_crypto_exposure_pct=0.70,
        maximum_symbol_exposure_pct=0.25,
        maximum_correlated_exposure_pct=0.45,
        maximum_open_risk_pct=0.10,
        maximum_open_positions=12,
        maximum_symbol_positions=3,
        full_allocation_score=0.68,
        reduced_allocation_score=0.50,
        minimal_allocation_score=0.35,
        full_multiplier=1.00,
        reduced_multiplier=0.75,
        minimal_multiplier=0.40,
        grid_multiplier=0.85,
        live_capable=True,
    ),
    AllocationProfile.PAPER_TEST: AllocationProfileConfig(
        maximum_crypto_exposure_pct=0.95,
        maximum_symbol_exposure_pct=0.60,
        maximum_correlated_exposure_pct=0.85,
        maximum_open_risk_pct=0.35,
        maximum_open_positions=30,
        maximum_symbol_positions=10,
        full_allocation_score=0.45,
        reduced_allocation_score=0.30,
        minimal_allocation_score=0.15,
        full_multiplier=1.00,
        reduced_multiplier=0.85,
        minimal_multiplier=0.60,
        grid_multiplier=1.00,
        live_capable=False,
    ),
}


def profile_config(profile: AllocationProfile) -> AllocationProfileConfig:
    config = PROFILE_CONFIGS[profile]
    config.validate()
    return config


@dataclass(frozen=True)
class PortfolioExposure:
    total_equity: float
    deployed_capital: float
    open_risk_amount: float
    crypto_exposure_pct: float
    symbol_exposure_pct: float
    correlated_exposure_pct: float
    open_positions: int
    symbol_positions: int

    def validate(self) -> None:
        require_finite(**{
            "total_equity": self.total_equity,
            "deployed_capital": self.deployed_capital,
            "open_risk_amount": self.open_risk_amount,
            "crypto_exposure_pct": self.crypto_exposure_pct,
            "symbol_exposure_pct": self.symbol_exposure_pct,
            "correlated_exposure_pct": self.correlated_exposure_pct,
        })
        if self.total_equity <= 0:
            raise ValueError("total_equity must be positive")
        for name, value in {
            "deployed_capital": self.deployed_capital,
            "open_risk_amount": self.open_risk_amount,
            "crypto_exposure_pct": self.crypto_exposure_pct,
            "symbol_exposure_pct": self.symbol_exposure_pct,
            "correlated_exposure_pct": self.correlated_exposure_pct,
        }.items():
            if value < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.open_positions < 0:
            raise ValueError("open_positions cannot be negative")
        if self.symbol_positions < 0:
            raise ValueError("symbol_positions cannot be negative")


@dataclass(frozen=True)
class AllocationRequest:
    risk: RiskResult
    portfolio: PortfolioExposure
    decision_classification: DecisionClassification
    profile: AllocationProfile = AllocationProfile.BALANCED
    requested_capital: float | None = None
    live_execution_requested: bool = False

    def validate(self) -> None:
        self.portfolio.validate()
        profile_config(self.profile)
        require_finite(requested_capital=self.requested_capital)
        if self.requested_capital is not None and self.requested_capital <= 0:
            raise ValueError("requested_capital must be positive")


@dataclass(frozen=True)
class AllocationResult:
    symbol: str
    profile: AllocationProfile
    decision: AllocationDecision
    tier: AllocationTier
    allocation_score: float
    capital_multiplier: float
    approved_capital: float | None
    approved_risk_amount: float | None
    remaining_crypto_capacity: float
    remaining_symbol_capacity: float
    remaining_correlated_capacity: float
    remaining_open_risk_capacity: float
    blockers: tuple[str, ...]
    reasons: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def approved_for_execution_policy(self) -> bool:
        return self.decision in {
            AllocationDecision.APPROVED,
            AllocationDecision.REDUCED,
        }

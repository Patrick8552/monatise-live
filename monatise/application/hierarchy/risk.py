from __future__ import annotations

from datetime import datetime
from dataclasses import dataclass

from monatise.application.hierarchy.models import RiskProposal


@dataclass(frozen=True)
class PreparedRiskInputs:
    """Target-independent inputs; not a qualified RiskProposal or approval proof."""

    direction: str
    entry_zone_low: float
    entry_zone_high: float
    reference_entry: float
    structural_invalidation: float
    volatility_buffer: float
    estimated_spread_allowance: float
    estimated_slippage_allowance: float
    final_stop: float
    minimum_reward_to_risk: float
    movement_tolerance: float
    expires_at: datetime

    def complete(self, target_liquidity: float) -> RiskProposal:
        risk = self.reference_entry - self.final_stop if self.direction == "long" else self.final_stop - self.reference_entry
        reward = target_liquidity - self.reference_entry if self.direction == "long" else self.reference_entry - target_liquidity
        if risk <= 0 or reward <= 0:
            raise ValueError("stop and target are inconsistent with direction")
        return RiskProposal(
            self.entry_zone_low, self.entry_zone_high, self.reference_entry,
            self.structural_invalidation, self.volatility_buffer,
            self.estimated_spread_allowance, self.estimated_slippage_allowance,
            self.final_stop, target_liquidity, self.minimum_reward_to_risk,
            reward / risk, self.movement_tolerance, self.expires_at, estimates_observed=False,
        )


class StructuralRiskInputBuilder:
    """Construct structural proposals; the canonical Risk Engine remains the approver."""

    def __init__(self, *, minimum_reward_to_risk: float = 1.5, atr_multiplier: float = 1.0, spread_allowance_pct: float = 0.0002, slippage_allowance_pct: float = 0.0003) -> None:
        if minimum_reward_to_risk <= 0 or atr_multiplier <= 0:
            raise ValueError("risk and ATR multipliers must be positive")
        if spread_allowance_pct < 0 or slippage_allowance_pct < 0:
            raise ValueError("cost allowances cannot be negative")
        self.minimum_reward_to_risk = minimum_reward_to_risk
        self.atr_multiplier = atr_multiplier
        self.spread_allowance_pct = spread_allowance_pct
        self.slippage_allowance_pct = slippage_allowance_pct

    def build(self, *, direction: str, entry_zone_low: float, entry_zone_high: float, structural_invalidation: float, target_liquidity: float, atr: float, movement_tolerance_pct: float, expires_at: datetime, reference_entry: float | None = None) -> RiskProposal:
        return self.prepare(
            direction=direction, entry_zone_low=entry_zone_low, entry_zone_high=entry_zone_high,
            structural_invalidation=structural_invalidation, atr=atr,
            movement_tolerance_pct=movement_tolerance_pct, expires_at=expires_at,
            reference_entry=reference_entry,
        ).complete(target_liquidity)

    def prepare(self, *, direction: str, entry_zone_low: float, entry_zone_high: float, structural_invalidation: float, atr: float, movement_tolerance_pct: float, expires_at: datetime, reference_entry: float | None = None) -> PreparedRiskInputs:
        normalized = direction.strip().lower()
        if normalized not in {"long", "short"}:
            raise ValueError("structural risk proposals require long or short direction")
        if entry_zone_low <= 0 or entry_zone_high <= 0 or atr < 0 or movement_tolerance_pct < 0:
            raise ValueError("prices and risk inputs must be non-negative")
        reference = (entry_zone_low + entry_zone_high) / 2 if reference_entry is None else reference_entry
        if not entry_zone_low <= reference <= entry_zone_high:
            raise ValueError("reference entry must be inside entry zone")
        volatility = atr * self.atr_multiplier
        spread = reference * self.spread_allowance_pct
        slippage = reference * self.slippage_allowance_pct
        buffer = volatility + spread + slippage
        final_stop = structural_invalidation - buffer if normalized == "long" else structural_invalidation + buffer
        risk = reference - final_stop if normalized == "long" else final_stop - reference
        if risk <= 0:
            raise ValueError("stop and target are inconsistent with direction")
        return PreparedRiskInputs(
            normalized, entry_zone_low, entry_zone_high, reference, structural_invalidation,
            volatility, spread, slippage, final_stop, self.minimum_reward_to_risk,
            reference * movement_tolerance_pct, expires_at,
        )

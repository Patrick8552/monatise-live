from __future__ import annotations

from datetime import datetime

from monatise.application.hierarchy.models import RiskProposal


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

    def build(self, *, direction: str, entry_zone_low: float, entry_zone_high: float, structural_invalidation: float, target_liquidity: float, atr: float, movement_tolerance_pct: float, expires_at: datetime) -> RiskProposal:
        normalized = direction.strip().lower()
        if normalized not in {"long", "short"}:
            raise ValueError("structural risk proposals require long or short direction")
        if entry_zone_low <= 0 or entry_zone_high <= 0 or atr < 0 or movement_tolerance_pct < 0:
            raise ValueError("prices and risk inputs must be non-negative")
        reference = (entry_zone_low + entry_zone_high) / 2
        volatility = atr * self.atr_multiplier
        spread = reference * self.spread_allowance_pct
        slippage = reference * self.slippage_allowance_pct
        buffer = volatility + spread + slippage
        final_stop = structural_invalidation - buffer if normalized == "long" else structural_invalidation + buffer
        risk = reference - final_stop if normalized == "long" else final_stop - reference
        reward = target_liquidity - reference if normalized == "long" else reference - target_liquidity
        if risk <= 0 or reward <= 0:
            raise ValueError("stop and target are inconsistent with direction")
        reward_risk = reward / risk
        return RiskProposal(
            entry_zone_low, entry_zone_high, reference, structural_invalidation, volatility, spread, slippage,
            final_stop, target_liquidity, self.minimum_reward_to_risk, reward_risk,
            reference * movement_tolerance_pct, expires_at, estimates_observed=False,
        )


from __future__ import annotations

from collections import defaultdict
from statistics import mean

from monatise.engines.portfolio_intelligence.models import (
    PortfolioHealth,
    PortfolioIntelligenceRequest,
    PortfolioIntelligenceResult,
    PortfolioRiskFlag,
)


class PortfolioIntelligenceEngine:
    """Evaluates crypto portfolio concentration and cross-position risk.

    The engine is read-only. It does not resize, close, hedge, or execute
    positions.
    """

    def assess(
        self,
        request: PortfolioIntelligenceRequest,
    ) -> PortfolioIntelligenceResult:
        request.validate()

        positions = list(request.positions)
        reasons: list[str] = []
        blockers: list[str] = []
        flags: list[PortfolioRiskFlag] = []

        if not positions:
            return PortfolioIntelligenceResult(
                health=PortfolioHealth.HEALTHY,
                portfolio_heat_pct=0.0,
                gross_notional=0.0,
                net_directional_notional=0.0,
                weighted_leverage=0.0,
                largest_symbol_exposure_pct=0.0,
                largest_correlation_group_pct=0.0,
                low_liquidity_exposure_pct=0.0,
                flags=(PortfolioRiskFlag.NONE,),
                blockers=(),
                reasons=("portfolio has no open positions",),
                metrics={},
                metadata={
                    "engine_scope": "crypto_only",
                    "execution_enabled": False,
                },
            )

        gross_notional = sum(position.notional for position in positions)
        total_risk = sum(position.risk_amount for position in positions)
        portfolio_heat_pct = total_risk / request.total_equity

        long_notional = sum(
            position.notional
            for position in positions
            if position.side == "long"
        )
        short_notional = sum(
            position.notional
            for position in positions
            if position.side == "short"
        )
        net_directional_notional = abs(long_notional - short_notional)
        directional_pct = (
            net_directional_notional / gross_notional
            if gross_notional > 0
            else 0.0
        )

        weighted_leverage = (
            sum(position.notional * position.leverage for position in positions)
            / gross_notional
            if gross_notional > 0
            else 0.0
        )

        symbol_totals: dict[str, float] = defaultdict(float)
        group_totals: dict[str, float] = defaultdict(float)

        low_liquidity_notional = 0.0

        for position in positions:
            symbol_totals[position.symbol.upper()] += position.notional
            if position.correlation_group:
                group_totals[position.correlation_group] += position.notional
            if (position.liquidity_tier or "").lower() in {"low", "illiquid"}:
                low_liquidity_notional += position.notional

        largest_symbol_notional = max(symbol_totals.values(), default=0.0)
        largest_symbol_exposure_pct = (
            largest_symbol_notional / request.total_equity
        )

        largest_group_notional = max(group_totals.values(), default=0.0)
        largest_correlation_group_pct = (
            largest_group_notional / request.total_equity
        )

        low_liquidity_exposure_pct = (
            low_liquidity_notional / request.total_equity
        )

        if portfolio_heat_pct > request.maximum_total_risk_pct:
            flags.append(PortfolioRiskFlag.HIGH_TOTAL_RISK)
            blockers.append(
                f"portfolio heat {portfolio_heat_pct:.2%} exceeds "
                f"maximum {request.maximum_total_risk_pct:.2%}"
            )

        if (
            largest_symbol_exposure_pct
            > request.maximum_symbol_notional_pct
        ):
            flags.append(PortfolioRiskFlag.SYMBOL_CONCENTRATION)
            blockers.append(
                f"largest symbol exposure {largest_symbol_exposure_pct:.2%} "
                f"exceeds maximum {request.maximum_symbol_notional_pct:.2%}"
            )

        if (
            largest_correlation_group_pct
            > request.maximum_correlation_group_pct
        ):
            flags.append(PortfolioRiskFlag.CORRELATION_CLUSTER)
            blockers.append(
                "correlation-group exposure exceeds configured maximum"
            )

        if directional_pct > request.maximum_directional_notional_pct:
            flags.append(PortfolioRiskFlag.DIRECTIONAL_CROWDING)
            reasons.append(
                f"directional crowding is {directional_pct:.2%}"
            )

        if weighted_leverage > request.maximum_weighted_leverage:
            flags.append(PortfolioRiskFlag.LEVERAGE_CONCENTRATION)
            blockers.append(
                f"weighted leverage {weighted_leverage:.2f} exceeds "
                f"maximum {request.maximum_weighted_leverage:.2f}"
            )

        if (
            low_liquidity_exposure_pct
            > request.maximum_low_liquidity_notional_pct
        ):
            flags.append(PortfolioRiskFlag.LIQUIDITY_CONCENTRATION)
            blockers.append(
                "low-liquidity exposure exceeds configured maximum"
            )

        if self._has_expiry_cluster(
            positions,
            request.expiry_cluster_window_seconds,
        ):
            flags.append(PortfolioRiskFlag.EXPIRY_CLUSTER)
            reasons.append(
                "multiple positions expire inside the same narrow time window"
            )

        if not flags:
            flags.append(PortfolioRiskFlag.NONE)
            reasons.append("portfolio concentration is within configured limits")

        warning_count = sum(
            flag in {
                PortfolioRiskFlag.DIRECTIONAL_CROWDING,
                PortfolioRiskFlag.EXPIRY_CLUSTER,
            }
            for flag in flags
        )

        if blockers:
            health = (
                PortfolioHealth.BLOCKED
                if len(blockers) >= 2
                else PortfolioHealth.FRAGILE
            )
        elif warning_count:
            health = PortfolioHealth.ELEVATED
        else:
            health = PortfolioHealth.HEALTHY

        return PortfolioIntelligenceResult(
            health=health,
            portfolio_heat_pct=round(portfolio_heat_pct, 6),
            gross_notional=round(gross_notional, 8),
            net_directional_notional=round(net_directional_notional, 8),
            weighted_leverage=round(weighted_leverage, 4),
            largest_symbol_exposure_pct=round(
                largest_symbol_exposure_pct,
                6,
            ),
            largest_correlation_group_pct=round(
                largest_correlation_group_pct,
                6,
            ),
            low_liquidity_exposure_pct=round(
                low_liquidity_exposure_pct,
                6,
            ),
            flags=tuple(dict.fromkeys(flags)),
            blockers=tuple(dict.fromkeys(blockers)),
            reasons=tuple(reasons),
            metrics={
                "long_notional": round(long_notional, 8),
                "short_notional": round(short_notional, 8),
                "directional_pct": round(directional_pct, 6),
                "total_risk_amount": round(total_risk, 8),
                "position_count": float(len(positions)),
            },
            metadata={
                "engine_scope": "crypto_only",
                "execution_enabled": False,
                "read_only": True,
            },
        )

    @staticmethod
    def _has_expiry_cluster(
        positions,
        window_seconds: int,
    ) -> bool:
        expiries = sorted(
            position.signal_expires_at_epoch
            for position in positions
            if position.signal_expires_at_epoch is not None
        )

        if len(expiries) < 2:
            return False

        for first, second in zip(expiries, expiries[1:]):
            if second - first <= window_seconds:
                return True
        return False

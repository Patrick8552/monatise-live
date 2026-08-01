from __future__ import annotations

from monatise.engines.capital_allocation.models import AllocationDecision
from monatise.engines.decision.models import DecisionClassification
from monatise.engines.execution_policy.models import ExecutionDecision
from monatise.engines.reporting_intelligence.models import (
    ReportChannel,
    ReportRequest,
    ReportResult,
    ReportSection,
    ReportSeverity,
)
from monatise.engines.risk_validation.models import RiskDecision


class ReportingIntelligenceEngine:
    """Builds explainable, channel-specific reports from engine outputs.

    This engine is read-only. It cannot change, override, approve, reject,
    or execute any setup.
    """

    def build(self, request: ReportRequest) -> ReportResult:
        request.validate()

        sections = (
            self._market_section(request),
            self._macro_section(request),
            self._regime_section(request),
            self._liquidity_section(request),
            self._structure_section(request),
            self._fibonacci_section(request),
            self._order_flow_section(request),
            self._rsi_section(request),
            self._decision_section(request),
            self._risk_section(request),
            self._allocation_section(request),
            self._execution_section(request),
            self._portfolio_section(request),
        )

        blockers = self._blockers(request)
        warnings = self._warnings(request)
        severity = self._overall_severity(request, blockers)
        headline = self._headline(request)
        summary = self._summary(request, blockers, warnings)
        trace = self._decision_trace(request)

        payload = self._payload(
            request=request,
            sections=sections,
            blockers=blockers,
            warnings=warnings,
            trace=trace,
        )

        return ReportResult(
            symbol=request.market.symbol,
            channel=request.channel,
            headline=headline,
            severity=severity,
            summary=summary,
            sections=sections,
            decision_trace=trace,
            blockers=blockers,
            warnings=warnings,
            payload=payload,
            generated_at=request.generated_at,
            metadata={
                "engine_scope": "crypto_only",
                "read_only": True,
                "decision_mutation_enabled": False,
                "execution_enabled": False,
                "include_full_evidence": request.include_full_evidence,
                "include_debug_metadata": request.include_debug_metadata,
            },
        )

    @staticmethod
    def _market_section(request: ReportRequest) -> ReportSection:
        quality = request.market.quality
        return ReportSection(
            name="market_data",
            summary=(
                f"{request.market.symbol} at {request.market.price}; "
                f"data status {quality.status.value}"
            ),
            severity=(
                ReportSeverity.INFO
                if quality.usable
                else ReportSeverity.BLOCKED
            ),
            details={
                "price": request.market.price,
                "interval": request.market.interval,
                "source": quality.source,
                "age_seconds": quality.age_seconds,
                "issues": quality.issues,
            },
        )

    @staticmethod
    def _macro_section(request: ReportRequest) -> ReportSection:
        return ReportSection(
            name="macro",
            summary=(
                f"macro bias {request.macro.bias.value}; "
                f"risk {request.macro.risk_state.value}"
            ),
            severity=(
                ReportSeverity.BLOCKED
                if request.macro.blocks_new_analysis
                else ReportSeverity.INFO
            ),
            score=request.macro.conviction,
            details={
                "score": request.macro.score,
                "reasons": request.macro.reasons,
            },
        )

    @staticmethod
    def _regime_section(request: ReportRequest) -> ReportSection:
        return ReportSection(
            name="regime",
            summary=(
                f"regime {request.regime.state.value}; "
                f"confidence {request.regime.confidence.value}"
            ),
            severity=(
                ReportSeverity.WARNING
                if not request.regime.permits_liquidity_analysis
                else ReportSeverity.INFO
            ),
            score=request.regime.score,
            details=request.regime.metrics,
        )

    @staticmethod
    def _liquidity_section(request: ReportRequest) -> ReportSection:
        return ReportSection(
            name="liquidity",
            summary=(
                f"{len(request.liquidity.buy_side_levels)} buy-side and "
                f"{len(request.liquidity.sell_side_levels)} sell-side levels mapped"
            ),
            severity=ReportSeverity.INFO,
            details={
                "nearest_buy_side": (
                    request.liquidity.nearest_buy_side.price
                    if request.liquidity.nearest_buy_side else None
                ),
                "nearest_sell_side": (
                    request.liquidity.nearest_sell_side.price
                    if request.liquidity.nearest_sell_side else None
                ),
                "confirmed_sweep": request.sweep.has_confirmed_sweep,
                "sweep_reasons": request.sweep.reasons,
            },
        )

    @staticmethod
    def _structure_section(request: ReportRequest) -> ReportSection:
        return ReportSection(
            name="market_structure",
            summary=(
                f"{request.structure.state.value} with "
                f"{request.structure.bias.value} bias"
            ),
            severity=(
                ReportSeverity.WARNING
                if not request.structure.directional
                else ReportSeverity.INFO
            ),
            score=request.structure.confidence,
            details={
                "latest_event": (
                    request.structure.latest_event.break_type.value
                    if request.structure.latest_event else None
                ),
                "reclaim": (
                    request.reclaim.strongest_event.status.value
                    if request.reclaim.strongest_event else None
                ),
                "active_demand": request.zones.active_demand is not None,
                "active_supply": request.zones.active_supply is not None,
            },
        )

    @staticmethod
    def _fibonacci_section(request: ReportRequest) -> ReportSection:
        return ReportSection(
            name="fibonacci",
            summary=(
                "validated anchor available"
                if request.fibonacci.has_valid_anchor
                else "no valid Fibonacci anchor"
            ),
            severity=(
                ReportSeverity.INFO
                if request.fibonacci.has_valid_anchor
                else ReportSeverity.WARNING
            ),
            score=(
                request.fibonacci.primary_anchor.score
                if request.fibonacci.primary_anchor else 0.0
            ),
            details={
                "direction": request.fibonacci.direction.value,
                "active_zone": (
                    request.fibonacci.active_zone.zone_type.value
                    if request.fibonacci.active_zone else None
                ),
                "invalidation": (
                    request.fibonacci.invalidation_level.price
                    if request.fibonacci.invalidation_level else None
                ),
            },
        )

    @staticmethod
    def _order_flow_section(request: ReportRequest) -> ReportSection:
        return ReportSection(
            name="order_flow",
            summary=(
                f"{request.order_flow.bias.value}; "
                f"{request.order_flow.participation.value}; "
                f"health {request.order_flow.health.value}"
            ),
            severity=(
                ReportSeverity.WARNING
                if request.order_flow.health.value
                in {"fragile", "exhausted", "trapped", "unavailable"}
                else ReportSeverity.INFO
            ),
            score=request.order_flow.score,
            details={
                "timing_score": request.order_flow.execution_timing_score,
                "inputs_used": request.order_flow.inputs_used,
            },
        )

    @staticmethod
    def _rsi_section(request: ReportRequest) -> ReportSection:
        return ReportSection(
            name="rsi",
            summary=(
                f"RSI {request.rsi.current_rsi}; "
                f"{request.rsi.condition.value}; "
                f"{request.rsi.divergence.value}"
            ),
            severity=(
                ReportSeverity.WARNING
                if not request.rsi.usable
                else ReportSeverity.INFO
            ),
            score=request.rsi.confidence,
            details={
                "bias": request.rsi.bias.value,
                "reasons": request.rsi.reasons,
            },
        )

    @staticmethod
    def _decision_section(request: ReportRequest) -> ReportSection:
        return ReportSection(
            name="decision",
            summary=(
                f"{request.decision.classification.value} "
                f"{request.decision.direction.value}; "
                f"state {request.decision.state.value}"
            ),
            severity=(
                ReportSeverity.BLOCKED
                if request.decision.classification
                is DecisionClassification.NO_TRADE
                else ReportSeverity.APPROVED
            ),
            score=request.decision.conviction,
            details={
                "long_score": request.decision.long_score,
                "short_score": request.decision.short_score,
                "grid_score": request.decision.grid_score,
                "conflict_ratio": request.decision.conflict_ratio,
            },
        )

    @staticmethod
    def _risk_section(request: ReportRequest) -> ReportSection:
        return ReportSection(
            name="risk",
            summary=(
                f"risk decision {request.risk.decision.value}; "
                f"RR {request.risk.reward_risk}"
            ),
            severity={
                RiskDecision.APPROVED: ReportSeverity.APPROVED,
                RiskDecision.CONDITIONAL: ReportSeverity.WARNING,
                RiskDecision.REJECTED: ReportSeverity.BLOCKED,
            }[request.risk.decision],
            score=request.risk.risk_score,
            details={
                "entry": request.risk.validated_entry,
                "invalidation": request.risk.validated_invalidation,
                "target": request.risk.validated_target,
                "risk_amount": request.risk.risk_amount,
                "issues": tuple(issue.code for issue in request.risk.issues),
            },
        )

    @staticmethod
    def _allocation_section(request: ReportRequest) -> ReportSection:
        return ReportSection(
            name="capital_allocation",
            summary=(
                f"{request.allocation.profile.value} profile; "
                f"{request.allocation.decision.value}; "
                f"tier {request.allocation.tier.value}"
            ),
            severity=(
                ReportSeverity.BLOCKED
                if request.allocation.decision is AllocationDecision.BLOCKED
                else ReportSeverity.APPROVED
            ),
            score=request.allocation.allocation_score,
            details={
                "approved_capital": request.allocation.approved_capital,
                "approved_risk_amount": request.allocation.approved_risk_amount,
                "capital_multiplier": request.allocation.capital_multiplier,
            },
        )

    @staticmethod
    def _execution_section(request: ReportRequest) -> ReportSection:
        return ReportSection(
            name="execution_policy",
            summary=(
                f"mode {request.execution_policy.mode.value}; "
                f"decision {request.execution_policy.decision.value}"
            ),
            severity=(
                ReportSeverity.BLOCKED
                if request.execution_policy.decision
                is ExecutionDecision.BLOCKED
                else ReportSeverity.WARNING
            ),
            details={
                "proposal_available": request.execution_policy.proposal is not None,
                "blockers": request.execution_policy.blockers,
                "warnings": request.execution_policy.warnings,
                "adapter_submission_enabled": False,
            },
        )

    @staticmethod
    def _portfolio_section(request: ReportRequest) -> ReportSection:
        if request.portfolio is None:
            return ReportSection(
                name="portfolio",
                summary="portfolio intelligence unavailable",
                severity=ReportSeverity.WARNING,
                details={},
            )

        return ReportSection(
            name="portfolio",
            summary=(
                f"portfolio health {request.portfolio.health.value}; "
                f"heat {request.portfolio.portfolio_heat_pct:.2%}"
            ),
            severity=(
                ReportSeverity.BLOCKED
                if request.portfolio.health.value in {"fragile", "blocked"}
                else ReportSeverity.INFO
            ),
            details={
                "flags": tuple(flag.value for flag in request.portfolio.flags),
                "weighted_leverage": request.portfolio.weighted_leverage,
                "gross_notional": request.portfolio.gross_notional,
            },
        )

    @staticmethod
    def _blockers(request: ReportRequest) -> tuple[str, ...]:
        blockers = [
            *request.decision.blockers,
            *(issue.message for issue in request.risk.issues if issue.severity.value == "blocker"),
            *request.allocation.blockers,
            *request.execution_policy.blockers,
        ]
        if request.portfolio is not None:
            blockers.extend(request.portfolio.blockers)
        return tuple(dict.fromkeys(blockers))

    @staticmethod
    def _warnings(request: ReportRequest) -> tuple[str, ...]:
        warnings = [
            *(issue.message for issue in request.risk.issues if issue.severity.value == "warning"),
            *request.execution_policy.warnings,
        ]
        if not request.rsi.usable:
            warnings.append("RSI unavailable")
        return tuple(dict.fromkeys(warnings))

    @staticmethod
    def _overall_severity(
        request: ReportRequest,
        blockers: tuple[str, ...],
    ) -> ReportSeverity:
        if blockers:
            return ReportSeverity.BLOCKED
        if request.risk.decision is RiskDecision.APPROVED:
            return ReportSeverity.APPROVED
        return ReportSeverity.WARNING

    @staticmethod
    def _headline(request: ReportRequest) -> str:
        return (
            f"{request.market.symbol}: "
            f"{request.decision.classification.value.upper()} "
            f"{request.decision.direction.value.upper()}"
        )

    @staticmethod
    def _summary(
        request: ReportRequest,
        blockers: tuple[str, ...],
        warnings: tuple[str, ...],
    ) -> str:
        if blockers:
            return (
                f"Setup blocked with {len(blockers)} blocker(s). "
                f"Decision conviction {request.decision.conviction:.2f}."
            )
        if warnings:
            return (
                f"Setup passed hard checks with {len(warnings)} warning(s). "
                f"Risk score {request.risk.risk_score:.2f}."
            )
        return (
            f"Setup passed reporting checks. "
            f"Decision conviction {request.decision.conviction:.2f}; "
            f"risk score {request.risk.risk_score:.2f}."
        )

    @staticmethod
    def _decision_trace(request: ReportRequest) -> tuple[str, ...]:
        trace = [
            f"market_data:{request.market.quality.status.value}",
            f"macro:{request.macro.risk_state.value}",
            f"regime:{request.regime.state.value}",
            f"structure:{request.structure.state.value}",
            f"order_flow:{request.order_flow.health.value}",
            f"decision:{request.decision.classification.value}",
            f"risk:{request.risk.decision.value}",
            f"allocation:{request.allocation.decision.value}",
            f"execution_policy:{request.execution_policy.decision.value}",
        ]
        return tuple(trace)

    @staticmethod
    def _payload(
        *,
        request: ReportRequest,
        sections: tuple[ReportSection, ...],
        blockers: tuple[str, ...],
        warnings: tuple[str, ...],
        trace: tuple[str, ...],
    ) -> dict:
        base = {
            "symbol": request.market.symbol,
            "channel": request.channel.value,
            "classification": request.decision.classification.value,
            "direction": request.decision.direction.value,
            "conviction": request.decision.conviction,
            "risk_decision": request.risk.decision.value,
            "allocation_decision": request.allocation.decision.value,
            "execution_policy_decision": request.execution_policy.decision.value,
            "signal_expires_at": request.risk.signal_expires_at.isoformat(),
            "blockers": blockers,
            "warnings": warnings,
            "decision_trace": trace,
        }

        if request.channel is ReportChannel.TELEGRAM:
            base["compact_sections"] = tuple(
                {
                    "name": section.name,
                    "summary": section.summary,
                    "severity": section.severity.value,
                }
                for section in sections
            )
        else:
            base["sections"] = tuple(
                {
                    "name": section.name,
                    "summary": section.summary,
                    "severity": section.severity.value,
                    "score": section.score,
                    "details": section.details,
                }
                for section in sections
            )

        if request.include_full_evidence:
            base["decision_evidence"] = tuple(
                {
                    "source": item.source,
                    "score": item.score,
                    "direction": item.direction.value,
                    "weight": item.weight,
                    "reason": item.reason,
                }
                for item in request.decision.evidence
            )

        if request.include_debug_metadata:
            base["debug_metadata"] = {
                "market": request.market.metadata,
                "decision": request.decision.metadata,
                "risk": request.risk.metadata,
                "allocation": request.allocation.metadata,
                "execution_policy": request.execution_policy.metadata,
            }

        return base

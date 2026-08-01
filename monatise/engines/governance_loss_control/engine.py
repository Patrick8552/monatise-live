from __future__ import annotations

from datetime import timedelta, timezone

from monatise.engines.capital_allocation.models import AllocationDecision
from monatise.engines.execution_policy.models import ExecutionDecision
from monatise.engines.governance_loss_control.models import (
    GovernanceAction,
    GovernanceDecision,
    GovernanceRequest,
    GovernanceResult,
    GovernanceState,
)
from monatise.engines.portfolio_intelligence.models import PortfolioHealth
from monatise.engines.risk_validation.models import RiskDecision


class GovernanceLossControlEngine:
    """Final governance gate for system-wide loss and drawdown control.

    The engine may block or reduce new setup approval. It does not close
    positions, place orders, or submit exchange commands.
    """

    def assess(self, request: GovernanceRequest) -> GovernanceResult:
        request.validate()

        snapshot = request.snapshot
        blockers: list[str] = []
        warnings: list[str] = []
        reasons: list[str] = []
        actions: list[GovernanceAction] = []

        daily_pnl = (
            snapshot.daily_realized_pnl
            + snapshot.daily_unrealized_pnl
        )
        daily_loss = max(0.0, -daily_pnl)
        daily_loss_pct = daily_loss / snapshot.daily_start_equity

        total_drawdown = max(
            0.0,
            snapshot.initial_equity - snapshot.current_equity,
        )
        total_drawdown_pct = total_drawdown / snapshot.initial_equity

        observed_at = request.observed_at
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)

        cooldown_until = None

        if snapshot.kill_switch_active:
            blockers.append("kill switch is already active")
            actions.append(GovernanceAction.ACTIVATE_KILL_SWITCH)

        if snapshot.manual_freeze_active:
            blockers.append("manual governance freeze is active")
            actions.append(GovernanceAction.FREEZE_NEW_SETUPS)

        if daily_loss_pct >= request.maximum_daily_loss_pct:
            blockers.append(
                f"daily loss {daily_loss_pct:.2%} reached maximum "
                f"{request.maximum_daily_loss_pct:.2%}"
            )
            actions.append(GovernanceAction.FREEZE_NEW_SETUPS)

        if total_drawdown_pct >= request.maximum_total_drawdown_pct:
            blockers.append(
                f"total drawdown {total_drawdown_pct:.2%} reached maximum "
                f"{request.maximum_total_drawdown_pct:.2%}"
            )
            actions.append(GovernanceAction.ACTIVATE_KILL_SWITCH)

        if snapshot.consecutive_losses >= request.maximum_consecutive_losses:
            if snapshot.last_loss_at is not None:
                last_loss_at = snapshot.last_loss_at
                if last_loss_at.tzinfo is None:
                    last_loss_at = last_loss_at.replace(tzinfo=timezone.utc)
                cooldown_until = last_loss_at + timedelta(
                    minutes=request.cooldown_minutes
                )
            else:
                cooldown_until = observed_at + timedelta(
                    minutes=request.cooldown_minutes
                )
            if cooldown_until > observed_at:
                blockers.append(
                    f"consecutive losses reached "
                    f"{snapshot.consecutive_losses}"
                )
                actions.append(GovernanceAction.START_COOLDOWN)
            else:
                warnings.append(
                    "consecutive-loss threshold was reached, but cooldown has elapsed"
                )
                actions.append(GovernanceAction.REQUIRE_MANUAL_REVIEW)

        if snapshot.losses_last_24h >= request.maximum_losses_24h:
            blockers.append(
                f"losses in the last 24 hours reached "
                f"{snapshot.losses_last_24h}"
            )
            actions.append(GovernanceAction.REQUIRE_MANUAL_REVIEW)

        if (
            total_drawdown_pct >= request.caution_drawdown_pct
            and total_drawdown_pct < request.maximum_total_drawdown_pct
        ):
            warnings.append(
                f"drawdown {total_drawdown_pct:.2%} is in caution range"
            )
            actions.append(GovernanceAction.REDUCE_RISK)

        self._validate_upstream(request, blockers)

        if request.portfolio is not None:
            if request.portfolio.health in {
                PortfolioHealth.FRAGILE,
                PortfolioHealth.BLOCKED,
            }:
                blockers.append(
                    f"portfolio health is {request.portfolio.health.value}"
                )
            elif request.portfolio.health is PortfolioHealth.ELEVATED:
                warnings.append("portfolio health is elevated")
                actions.append(GovernanceAction.REDUCE_RISK)

        override_applied = False
        if blockers and request.allow_manual_override:
            non_overridable = any(
                text in blocker
                for blocker in blockers
                for text in (
                    "kill switch",
                    "total drawdown",
                    "manual governance freeze",
                    "risk validation decision",
                    "capital allocation decision",
                    "execution policy is blocked",
                    "portfolio health is fragile",
                    "portfolio health is blocked",
                )
            )
            if not non_overridable:
                override_applied = True
                warnings.extend(
                    f"manual override accepted for: {blocker}"
                    for blocker in blockers
                )
                blockers = []
                actions.append(GovernanceAction.REQUIRE_MANUAL_REVIEW)
                reasons.append("manual override accepted for overridable controls")

        if any(
            action is GovernanceAction.ACTIVATE_KILL_SWITCH
            for action in actions
        ):
            state = GovernanceState.KILL_SWITCH
            decision = GovernanceDecision.BLOCK
            multiplier = 0.0
        elif blockers:
            state = (
                GovernanceState.COOLDOWN
                if GovernanceAction.START_COOLDOWN in actions
                else GovernanceState.FROZEN
            )
            decision = GovernanceDecision.BLOCK
            multiplier = 0.0
        elif warnings or override_applied:
            state = GovernanceState.CAUTION
            decision = GovernanceDecision.REDUCE
            multiplier = request.caution_risk_multiplier
        else:
            state = GovernanceState.NORMAL
            decision = GovernanceDecision.ALLOW
            multiplier = 1.0
            actions.append(GovernanceAction.NONE)

        if decision is GovernanceDecision.BLOCK:
            reasons.append("governance controls blocked new setups")
        elif decision is GovernanceDecision.REDUCE:
            reasons.append("governance controls require reduced risk")
        else:
            reasons.append("governance controls permit normal operation")

        return GovernanceResult(
            symbol=request.risk.symbol,
            state=state,
            decision=decision,
            actions=tuple(dict.fromkeys(actions)),
            approved_risk_multiplier=round(multiplier, 4),
            daily_loss_pct=round(daily_loss_pct, 6),
            total_drawdown_pct=round(total_drawdown_pct, 6),
            cooldown_until=cooldown_until,
            blockers=tuple(dict.fromkeys(blockers)),
            warnings=tuple(dict.fromkeys(warnings)),
            reasons=tuple(reasons),
            metadata={
                "engine_scope": "crypto_only",
                "final_governance_gate": True,
                "execution_enabled": False,
                "position_closure_enabled": False,
                "automatic_override_enabled": False,
                "manual_override_applied": override_applied,
                "non_overridable_controls": (
                    "kill_switch",
                    "maximum_total_drawdown",
                    "manual_freeze",
                ),
            },
        )

    @staticmethod
    def _validate_upstream(
        request: GovernanceRequest,
        blockers: list[str],
    ) -> None:
        if request.risk.decision is not RiskDecision.APPROVED:
            blockers.append(
                f"risk validation decision is {request.risk.decision.value}"
            )

        if request.allocation.decision not in {
            AllocationDecision.APPROVED,
            AllocationDecision.REDUCED,
        }:
            blockers.append(
                f"capital allocation decision is "
                f"{request.allocation.decision.value}"
            )

        if request.execution_policy.decision is ExecutionDecision.BLOCKED:
            blockers.append("execution policy is blocked")

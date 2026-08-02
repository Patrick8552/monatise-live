from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from monatise.application.hierarchy.coordinator import ShadowComparison, ShadowHierarchyCoordinator
from monatise.application.hierarchy.evaluator import HierarchyLayerEvaluator, ShadowEvaluation
from monatise.application.hierarchy.lifecycle import HierarchyRepository
from monatise.application.hierarchy.models import TriggerState


class ShadowHierarchyService:
    """Coordinates shadow analysis and optional notification-only publication."""

    def __init__(self, coordinator: ShadowHierarchyCoordinator, evaluator: HierarchyLayerEvaluator, repository: HierarchyRepository, *, publisher: Callable[[str], Awaitable[Any]] | None = None) -> None:
        self.coordinator = coordinator
        self.evaluator = evaluator
        self.repository = repository
        self.publisher = publisher

    async def tick(self, symbol: str, *, observed_at: datetime | None = None, macro_degraded: bool = True) -> dict[str, Any]:
        now = observed_at or datetime.now(timezone.utc)
        snapshots = await self.coordinator.collect_due(symbol, watching=self.evaluator.watching(symbol), observed_at=now)
        if not snapshots:
            return self._result(symbol, (), None, duplicate=False)
        evaluation = self.evaluator.evaluate(symbol, snapshots, evaluated_at=now, macro_degraded=macro_degraded)
        for context in (
            evaluation.macro_context,
            evaluation.regime_4h if "4h" in snapshots else None,
            evaluation.strategy_1h if "1h" in snapshots else None,
            evaluation.setup_15m if "15m" in snapshots else None,
            evaluation.trigger_5m if "5m" in snapshots else None,
        ):
            if context is not None:
                await self.repository.append_context(context)

        duplicate = False
        trigger_id: str | None = None
        if evaluation.trigger_5m is not None and evaluation.trigger_5m.state is TriggerState.TRIGGER_CONFIRMED:
            claimed, trigger_id = await self.coordinator.claim_closed_trigger(
                trigger=evaluation.trigger_5m,
                setup_id=evaluation.setup_15m.identity.context_id,
                trigger_type="reclaim_or_structure_break",
            )
            duplicate = not claimed

        published = False
        publication_failed = False
        eligible = evaluation.validation is not None and evaluation.validation.eligible_for_shadow_decision
        if eligible and not duplicate and trigger_id is not None and self.coordinator.configuration.telegram_publish_enabled and self.publisher is not None:
            try:
                await self.publisher(self._format_notification(evaluation))
                published = True
            except Exception:
                publication_failed = True

        hierarchical_outcome = (
            "duplicate" if duplicate else
            evaluation.validation.outcome.value if evaluation.validation is not None else
            evaluation.trigger_5m.state.value if evaluation.trigger_5m is not None else
            evaluation.setup_15m.state.value if evaluation.setup_15m is not None else
            evaluation.strategy_1h.state.value if evaluation.strategy_1h is not None else
            "data_unavailable"
        )
        await self.coordinator.record_comparison(ShadowComparison(
            symbol.upper(), now, "not_sampled_same_tick", hierarchical_outcome,
            forming_candle_blocked=any("closed_candle_unavailable" in reason for reason in evaluation.reasons),
            duplicate_blocked=duplicate,
        ))
        return self._result(symbol, tuple(snapshots), evaluation, duplicate=duplicate, published=published, publication_failed=publication_failed)

    def _result(self, symbol: str, layers: tuple[str, ...], evaluation: ShadowEvaluation | None, *, duplicate: bool, published: bool = False, publication_failed: bool = False) -> dict[str, Any]:
        return {
            "symbol": symbol.upper(),
            "layers_observed": list(layers),
            "watching": evaluation.watching if evaluation else False,
            "setup_state": evaluation.setup_15m.state.value if evaluation and evaluation.setup_15m else None,
            "trigger_state": evaluation.trigger_5m.state.value if evaluation and evaluation.trigger_5m else None,
            "shadow_outcome": evaluation.validation.outcome.value if evaluation and evaluation.validation else None,
            "duplicate_blocked": duplicate,
            "shadow": True,
            "telegram_publish_enabled": self.coordinator.configuration.telegram_publish_enabled,
            "telegram_published": published,
            "telegram_publication_failed": publication_failed,
            "execution_enabled": False,
        }

    @staticmethod
    def _format_notification(evaluation: ShadowEvaluation) -> str:
        bundle = evaluation.bundle
        if bundle is None:
            raise ValueError("notification requires a validated evidence bundle")
        risk = bundle.risk_inputs
        direction = bundle.trigger_5m.direction.upper()
        return (
            f"Monatise HIERARCHY SHADOW — observation only, not a trade order\n"
            f"{bundle.symbol} | {direction} | 4H + 1H aligned | 15M setup confirmed | 5M trigger confirmed\n"
            f"Entry {risk.reference_entry:.8g} | Stop {risk.final_stop:.8g} | Target {risk.target_liquidity:.8g} | R:R {risk.calculated_reward_to_risk:.2f}\n"
            f"Strategy {bundle.strategy_version} | Evidence {bundle.bundle_id[:12]}"
        )

    @property
    def execution_enabled(self) -> bool:
        return False

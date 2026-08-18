from __future__ import annotations

from datetime import datetime, timezone
import asyncio
import logging
from typing import Any, Awaitable, Callable

from monatise.application.hierarchy.coordinator import ShadowComparison, ShadowHierarchyCoordinator
from monatise.application.hierarchy.evaluator import HierarchyLayerEvaluator, ShadowEvaluation
from monatise.application.hierarchy.lifecycle import HierarchyRepository
from monatise.application.hierarchy.models import TriggerState
from monatise.application.time_display import format_nigeria_time, nigeria_isoformat


LOGGER = logging.getLogger("monatise.hierarchy")


class ShadowHierarchyService:
    """Coordinates shadow analysis and optional notification-only publication."""

    def __init__(self, coordinator: ShadowHierarchyCoordinator, evaluator: HierarchyLayerEvaluator, repository: HierarchyRepository, *, publisher: Callable[[str], Awaitable[Any]] | None = None, current_price_provider: Callable[[str], float] | None = None) -> None:
        self.coordinator = coordinator
        self.evaluator = evaluator
        self.repository = repository
        self.publisher = publisher
        self.current_price_provider = current_price_provider

    async def tick(self, symbol: str, *, observed_at: datetime | None = None, macro_degraded: bool = True, market_context: dict[str, Any] | None = None) -> dict[str, Any]:
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
        eligible = evaluation.validation is not None and evaluation.validation.eligible_for_shadow_decision
        publication_available = self.coordinator.configuration.telegram_publish_enabled and self.publisher is not None
        if eligible and publication_available and evaluation.trigger_5m is not None and evaluation.trigger_5m.state is TriggerState.TRIGGER_CONFIRMED:
            claimed, trigger_id = await self.coordinator.claim_closed_trigger(
                trigger=evaluation.trigger_5m,
                setup_id=evaluation.setup_15m.identity.context_id,
                trigger_type="reclaim_or_structure_break",
            )
            duplicate = not claimed

        published = False
        publication_failed = False
        telegram_message_id: int | None = None
        if eligible and publication_available and not duplicate and trigger_id is not None:
            await self.repository.begin_publication(symbol=symbol, trigger_id=trigger_id, occurred_at=now)
            current_price = None
            if self.current_price_provider is not None:
                try:
                    current_price = await asyncio.to_thread(self.current_price_provider, symbol)
                except Exception:
                    LOGGER.warning("hierarchical CoinGlass current price unavailable", extra={"symbol": symbol.upper()})
            try:
                delivery_result = await self.publisher(self._format_notification(evaluation, publication_id=trigger_id, current_price=current_price, price_observed_at=now, market_context=market_context))
                telegram_message_id = self._telegram_message_id(delivery_result)
            except Exception as exc:
                publication_failed = True
                try:
                    await self.repository.record_publication(symbol=symbol, trigger_id=trigger_id, occurred_at=now, succeeded=False, error_type=type(exc).__name__)
                except Exception:
                    LOGGER.exception("failed to persist hierarchical Telegram publication failure", extra={"symbol": symbol.upper(), "trigger_id": trigger_id})
                LOGGER.exception("hierarchical Telegram publication failed", extra={"symbol": symbol.upper(), "trigger_id": trigger_id})
            else:
                # Do not reinterpret a post-delivery persistence failure as a
                # transport failure: the provider has already accepted it.
                published = True
                try:
                    await self.repository.record_publication(symbol=symbol, trigger_id=trigger_id, occurred_at=now, succeeded=True, telegram_message_id=telegram_message_id)
                except Exception:
                    publication_failed = True
                    LOGGER.exception("Telegram delivered but publication receipt persistence failed", extra={"symbol": symbol.upper(), "trigger_id": trigger_id, "telegram_message_id": telegram_message_id})

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
        return self._result(symbol, tuple(snapshots), evaluation, duplicate=duplicate, published=published, publication_failed=publication_failed, publication_id=trigger_id, telegram_message_id=telegram_message_id)

    def _result(self, symbol: str, layers: tuple[str, ...], evaluation: ShadowEvaluation | None, *, duplicate: bool, published: bool = False, publication_failed: bool = False, publication_id: str | None = None, telegram_message_id: int | None = None) -> dict[str, Any]:
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
            "publication_id": publication_id,
            "telegram_message_id": telegram_message_id,
            "execution_enabled": False,
        }

    @staticmethod
    def _format_notification(evaluation: ShadowEvaluation, *, publication_id: str, current_price: float | None = None, price_observed_at: datetime | None = None, price_source: str = "coinglass", market_context: dict[str, Any] | None = None) -> str:
        bundle = evaluation.bundle
        if bundle is None:
            raise ValueError("notification requires a validated evidence bundle")
        risk = bundle.risk_inputs
        direction = bundle.trigger_5m.direction.upper()
        validity_seconds = max(0, int((risk.expires_at - evaluation.evaluated_at).total_seconds()))
        validity_minutes = (validity_seconds + 59) // 60
        expiry = format_nigeria_time(risk.expires_at)
        observed = nigeria_isoformat(price_observed_at or evaluation.evaluated_at)
        current = f"{current_price:,.8f}".rstrip("0").rstrip(".") if current_price is not None else "unavailable"
        context = market_context or {}
        discovery = context.get("discovery") or {}
        derivatives = context.get("derivatives") or {}
        evidence = (
            f"Discovery score {float(discovery.get('score', 0)):.2f} | confidence: confirmed hierarchy\n"
            f"Funding {_display_metric(derivatives.get('funding_rate', discovery.get('funding_rate')))} | "
            f"OI ${_display_metric(derivatives.get('open_interest', discovery.get('open_interest_usd')))} "
            f"({float(discovery.get('open_interest_change_15m', 0)):+.2f}%/15m) | "
            f"Volume ${_display_metric(derivatives.get('derivatives_volume', discovery.get('volume_usd')))}\n"
            f"CVD {_display_metric(derivatives.get('cvd_change', derivatives.get('cvd')))} | "
            f"Liquidations ${_display_metric(derivatives.get('liquidation_volume'))} | "
            f"Order-book imbalance {_display_metric(derivatives.get('order_book_imbalance'))}"
        )
        return (
            f"Monatise HIERARCHY SHADOW — observation only, not a trade order\n"
            f"{bundle.symbol} | {direction} | {context.get('verified_market', 'CoinGlass verified futures market')}\n"
            f"15M directional thesis confirmed | 5M structure confirmed | 1M entry trigger refined\n"
            f"Current CoinGlass price: {current} | source {price_source} | observed {observed}\n"
            f"Entry {risk.reference_entry:.8g} | Stop {risk.final_stop:.8g} | Target {risk.target_liquidity:.8g} | R:R {risk.calculated_reward_to_risk:.2f}\n"
            f"{evidence}\n"
            f"Expires {expiry} | Valid for {validity_minutes} min\n"
            f"Strategy {bundle.strategy_version} | Evidence {bundle.bundle_id[:12]} | Publication {publication_id[:16]}\n"
            f"Analysis only — no trade executed"
        )

    @staticmethod
    def _telegram_message_id(delivery_result: Any) -> int | None:
        if isinstance(delivery_result, int) and not isinstance(delivery_result, bool):
            return delivery_result
        if isinstance(delivery_result, dict):
            value = delivery_result.get("message_id")
            return value if isinstance(value, int) and not isinstance(value, bool) else None
        return None

    @property
    def execution_enabled(self) -> bool:
        return False


def _display_metric(value: Any) -> str:
    try:
        return f"{float(value):,.4g}"
    except (TypeError, ValueError):
        return "unavailable"

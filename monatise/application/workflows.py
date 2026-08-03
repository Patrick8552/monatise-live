"""OpenClaw scheduling and Telegram delivery workflows (analysis-only)."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import datetime, timezone
from datetime import timedelta
from typing import Any, Awaitable, Callable, Protocol

from monatise.application.models import AnalysisRun, PipelineResult
from monatise.application.orchestrator import PipelineOrchestrator
from monatise.infrastructure.state_manager import StateKey
from monatise.infrastructure.task_scheduler import JobDefinition, RetryPolicy, ScheduleType


class TelegramTransport(Protocol):
    async def send_message(self, chat_id: str, text: str) -> Any: ...


class TelegramNotifier:
    def __init__(self, transport: TelegramTransport, chat_id: str) -> None:
        if not isinstance(chat_id, str) or not chat_id.strip():
            raise ValueError("Telegram chat_id is required")
        self._transport, self._chat_id = transport, chat_id

    async def deliver(self, result: PipelineResult) -> Any:
        text = self.format(result)
        return await self._transport.send_message(self._chat_id, text)

    async def deliver_safely(self, result: PipelineResult) -> bool:
        try:
            await self.deliver(result)
            return True
        except Exception:
            return False

    async def governance_alert(self, message: str) -> Any:
        return await self._alert("GOVERNANCE", message)

    async def health_alert(self, message: str) -> Any:
        return await self._alert("HEALTH", message)

    async def audit_notification(self, message: str) -> Any:
        return await self._alert("AUDIT", message)

    async def hierarchy_shadow_notification(self, message: str) -> Any:
        if not message.strip():
            raise ValueError("notification message is required")
        return await self._transport.send_message(self._chat_id, message)

    async def _alert(self, category: str, message: str) -> Any:
        if not message.strip():
            raise ValueError("notification message is required")
        return await self._transport.send_message(self._chat_id, f"Monatise {category}: {message}")

    @staticmethod
    def format(result: PipelineResult) -> str:
        outputs = result.context.outputs
        decision = outputs.get("decision")
        risk = outputs.get("risk_validation")
        market = outputs.get("market_data")

        if decision is None or risk is None:
            suffix = f" | blocked by {result.blocked_by}" if result.blocked_by else ""
            return (
                f"Monatise analysis: {result.symbol} | {result.status.value} | "
                f"stages {result.statistics.completed_stages}/20{suffix} | run {result.run_id}"
            )

        direction = _enum_value(getattr(decision, "direction", "none")).upper()
        classification = _enum_value(getattr(decision, "classification", "no_trade")).upper()
        conviction = float(getattr(decision, "conviction", 0.0) or 0.0)
        entry = getattr(risk, "validated_entry", None)
        stop = getattr(risk, "validated_invalidation", None)
        target = getattr(risk, "validated_target", None)
        reward_risk = getattr(risk, "reward_risk", None)
        expires_at = getattr(risk, "signal_expires_at", None)
        quality = getattr(market, "quality", None)
        source = getattr(quality, "source", "CoinGlass")
        reasons = tuple(getattr(decision, "reasons", ()) or ())[:3]

        lines = [
            f"Monatise signal: {result.symbol} {direction} ({classification})",
            f"Confidence: {conviction * 100:.0f}%",
            f"Entry: {_price(entry)} | Stop: {_price(stop)} | Target: {_price(target)}",
        ]
        if reward_risk is not None:
            lines.append(f"Reward/risk: {float(reward_risk):.2f}")
        if expires_at is not None:
            lines.append(f"Expires: {expires_at.astimezone(timezone.utc):%Y-%m-%d %H:%M UTC}")
        lines.append(f"Data: {source} | Status: {result.status.value}")
        if reasons:
            lines.append("Why: " + "; ".join(str(reason) for reason in reasons))
        lines.append(f"Run: {result.run_id}")
        return "\n".join(lines)

    @property
    def execution_enabled(self) -> bool:
        return False


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _price(value: Any) -> str:
    if value is None:
        return "pending"
    return f"{float(value):,.8f}".rstrip("0").rstrip(".")


@dataclass(frozen=True)
class OpenClawWorkflow:
    orchestrator: PipelineOrchestrator
    run_factory: Callable[[], AnalysisRun | Awaitable[AnalysisRun]]
    notifier: TelegramNotifier | None = None
    maximum_request_age_seconds: float = 300.0

    def __post_init__(self) -> None:
        if self.maximum_request_age_seconds <= 0:
            raise ValueError("maximum_request_age_seconds must be positive")
        if not callable(self.run_factory):
            raise ValueError("run_factory must be callable")

    async def schedule(self, scheduler: Any, *, job_id: str, interval_seconds: float, state: Any | None = None) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")

        async def task() -> PipelineResult:
            if state is not None:
                await state.set(StateKey("openclaw_workflows", job_id), {"status": "running", "updated_at": datetime.now(timezone.utc).isoformat()})
            try:
                result = await self.execute()
            except Exception:
                if state is not None:
                    await state.set(StateKey("openclaw_workflows", job_id), {"status": "failed", "updated_at": datetime.now(timezone.utc).isoformat()})
                raise
            if state is not None:
                await state.set(StateKey("openclaw_workflows", job_id), {"status": result.status.value, "run_id": result.run_id, "updated_at": datetime.now(timezone.utc).isoformat()})
            return result

        await scheduler.register(JobDefinition(job_id, f"OpenClaw crypto analysis {job_id}", task, ScheduleType.INTERVAL, interval=timedelta(seconds=interval_seconds), retry_policy=RetryPolicy(maximum_attempts=3), tags=("openclaw", "crypto", "analysis"), metadata={"execution_enabled": False}))

    async def execute(self) -> PipelineResult:
        candidate = self.run_factory()
        run = await candidate if inspect.isawaitable(candidate) else candidate
        if not isinstance(run, AnalysisRun):
            raise TypeError("run_factory must return AnalysisRun")
        age = (datetime.now(timezone.utc) - run.requested_at).total_seconds()
        if age < -60:
            raise ValueError("scheduled analysis request is in the future")
        if age > self.maximum_request_age_seconds:
            raise ValueError("scheduled analysis request is stale")
        result = await self.orchestrator.run(run)
        if self.notifier is not None:
            await self.notifier.deliver_safely(result)
        return result

    @property
    def execution_enabled(self) -> bool:
        return False

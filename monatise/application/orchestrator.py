"""Single-entry, observable orchestration of the canonical engine pipeline."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from time import perf_counter
from typing import Any, Callable

from monatise.application.models import AnalysisRun, PipelineContext, PipelineFailure, PipelineResult, PipelineStage, PipelineStatistics
from monatise.application.registry import EngineRegistry
from monatise.infrastructure.audit_database import AuditAction, AuditActor, AuditRecordType
from monatise.infrastructure.event_bus import DomainEvent, EventBus, EventPriority
from monatise.infrastructure.observability import LogLevel
from monatise.infrastructure.security import AccessDecision
from monatise.infrastructure.state_manager import StateKey


@dataclass(frozen=True)
class ApplicationInfrastructure:
    container: Any
    event_bus: EventBus
    configuration: Any
    plugins: Any
    scheduler: Any
    state: Any
    audit: Any
    feature_flags: Any
    security: Any
    observability: Any


class _InvocationFailure(RuntimeError):
    def __init__(self, cause: Exception, attempt: int) -> None:
        super().__init__(str(cause))
        self.cause = cause
        self.attempt = attempt


def _json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return {
            item.name: _json_safe(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


class PipelineOrchestrator:
    """Coordinates engines without modifying or bypassing their decisions."""

    def __init__(self, registry: EngineRegistry, infrastructure: ApplicationInfrastructure, *, stage_timeout_seconds: float = 30.0) -> None:
        errors = registry.validate()
        if errors:
            raise ValueError("invalid engine registry: " + "; ".join(errors))
        if stage_timeout_seconds <= 0:
            raise ValueError("stage_timeout_seconds must be positive")
        self.registry = registry
        self.infrastructure = infrastructure
        self.stage_timeout_seconds = stage_timeout_seconds

    async def run(self, run: AnalysisRun) -> PipelineResult:
        started_at = datetime.now(timezone.utc)
        started = perf_counter()
        context = PipelineContext(run=run)
        durations: dict[str, float] = {}
        attempts: dict[str, int] = {}
        failure: PipelineFailure | None = None
        blocked_by: str | None = None
        status = PipelineStage.RUNNING

        decision = self.infrastructure.security.authorize(
            run.metadata.actor_id, resource="analysis_pipeline", action="run", correlation_id=run.correlation_id,
        )
        if decision is not AccessDecision.ALLOW:
            failure = PipelineFailure("application", "authorization_denied", "actor is not authorized to run analysis", False, 1)
            status = PipelineStage.FAILED
            return await self._finish(run, context, status, failure, None, started_at, started, durations, attempts)

        await self._event(run, "analysis.run.started", {"run_id": run.run_id})
        await self._audit(run, AuditAction.CREATED, {"status": "started"})
        await self.infrastructure.state.set(StateKey("analysis_runs", run.run_id), {"status": "running", "symbol": run.symbol})
        await self.infrastructure.observability.log(LogLevel.INFO, "analysis pipeline started", source=run.metadata.source, correlation_id=run.correlation_id, symbol=run.symbol, fields={"run_id": run.run_id})

        for registration in self.registry.ordered():
            stage_started = perf_counter()
            attempts[registration.name] = 1
            if self._persist_stage_progress(run):
                await self._event(run, "analysis.stage.started", {"engine": registration.name})
            try:
                if registration.name not in run.stage_inputs:
                    raise KeyError(f"stage input is missing: {registration.name}")
                request_or_factory = run.stage_inputs[registration.name]
                request = request_or_factory(context) if callable(request_or_factory) else request_or_factory
                validator = getattr(request, "validate", None)
                if callable(validator):
                    validator()
                output, attempt = await self._invoke_with_retry(registration.name, registration.method, request, registration.retryable, run)
                attempts[registration.name] = attempt
                if output is None:
                    raise ValueError("engine returned no result")
                output_validator = getattr(output, "validate", None)
                if callable(output_validator):
                    output_validator()
                output_symbol = getattr(output, "symbol", run.symbol)
                if str(output_symbol).upper() != run.symbol:
                    raise ValueError(f"engine returned mismatched symbol: {output_symbol}")
                context = context.with_output(registration.name, output)
                durations[registration.name] = (perf_counter() - stage_started) * 1000
                await self.infrastructure.observability.histogram("pipeline.stage.duration_ms", durations[registration.name], labels={"engine": registration.name, "status": "completed"})
                if self._persist_stage_progress(run):
                    await self._event(run, "analysis.stage.completed", {"engine": registration.name, "duration_ms": durations[registration.name]})
                if registration.blocking is not None and registration.blocking(output):
                    blocked_by = registration.name
                    status = PipelineStage.BLOCKED
                    await self._event(run, "analysis.run.blocked", {"engine": registration.name}, priority=EventPriority.HIGH)
                    await self._audit(run, AuditAction.BLOCKED, {"engine": registration.name, "result": _json_safe(output)})
                    break
            except Exception as exc:
                durations[registration.name] = (perf_counter() - stage_started) * 1000
                cause = exc.cause if isinstance(exc, _InvocationFailure) else exc
                attempt = exc.attempt if isinstance(exc, _InvocationFailure) else attempts[registration.name]
                attempts[registration.name] = attempt
                failure = PipelineFailure(registration.name, type(cause).__name__, str(cause), registration.retryable, attempt)
                status = PipelineStage.FAILED
                await self._event(run, "analysis.stage.failed", {"engine": registration.name, "error_type": type(cause).__name__}, priority=EventPriority.HIGH)
                await self._audit(run, AuditAction.FAILED, {"engine": registration.name, "error_type": type(cause).__name__, "message": str(cause)})
                break
        else:
            status = PipelineStage.COMPLETED

        return await self._finish(run, context, status, failure, blocked_by, started_at, started, durations, attempts)

    async def _invoke_with_retry(self, name: str, method: str, request: Any, retryable: bool, run: AnalysisRun) -> tuple[Any, int]:
        maximum = run.metadata.maximum_attempts if retryable else 1
        last_error: Exception | None = None
        for attempt in range(1, maximum + 1):
            try:
                engine = self.registry.resolve(name)
                invocation = getattr(engine, method)

                async def invoke() -> Any:
                    if inspect.iscoroutinefunction(invocation):
                        return await invocation(request)
                    result = await asyncio.to_thread(invocation, request)
                    return await result if inspect.isawaitable(result) else result

                result = await asyncio.wait_for(invoke(), timeout=self.stage_timeout_seconds)
                return result, attempt
            except Exception as exc:
                last_error = exc
                if attempt < maximum and run.metadata.retry_delay_seconds:
                    await asyncio.sleep(run.metadata.retry_delay_seconds * attempt)
        assert last_error is not None
        raise _InvocationFailure(last_error, maximum) from last_error

    async def _finish(self, run: AnalysisRun, context: PipelineContext, status: PipelineStage, failure: PipelineFailure | None, blocked_by: str | None, started_at: datetime, started: float, durations: dict[str, float], attempts: dict[str, int]) -> PipelineResult:
        finished_at = datetime.now(timezone.utc)
        statistics = PipelineStatistics((perf_counter() - started) * 1000, durations, attempts, len(context.outputs))
        result = PipelineResult(run.run_id, run.correlation_id, run.symbol, status, context, statistics, failure, blocked_by, started_at, finished_at)
        await self.infrastructure.state.set(StateKey("analysis_runs", run.run_id), {"status": status.value, "symbol": run.symbol, "blocked_by": blocked_by, "failure": _json_safe(failure)})
        await self.infrastructure.observability.counter("pipeline.runs.total", labels={"status": status.value})
        await self.infrastructure.observability.histogram("pipeline.run.duration_ms", statistics.total_duration_ms, labels={"status": status.value})
        await self._event(run, f"analysis.run.{status.value}", {"run_id": run.run_id, "completed_stages": statistics.completed_stages})
        if status is PipelineStage.COMPLETED:
            await self._audit(run, AuditAction.APPROVED, {"status": status.value, "completed_stages": statistics.completed_stages})
        return result

    async def _event(self, run: AnalysisRun, event_type: str, payload: dict[str, Any], priority: EventPriority = EventPriority.NORMAL) -> None:
        await self.infrastructure.event_bus.publish(DomainEvent(event_type, _json_safe(payload), run.metadata.source, run.symbol, run.correlation_id, priority=priority), idempotency_key=f"{run.run_id}:{event_type}:{payload.get('engine', '')}")

    @staticmethod
    def _persist_stage_progress(run: AnalysisRun) -> bool:
        """Keep read-only dashboard refreshes out of the durable-event hot path.

        Run-level, blocked, and failed events remain durable. Successful stage
        progress is already represented in the returned result and final audit
        record, so writing two PostgreSQL events per stage only delays the web
        response without changing its decision.
        """
        return run.metadata.source != "monatise.web"

    async def _audit(self, run: AnalysisRun, action: AuditAction, payload: dict[str, Any]) -> None:
        version = getattr(self.infrastructure.configuration.snapshot(), "version", None)
        await self.infrastructure.audit.append(record_type=AuditRecordType.SYSTEM, action=action, actor=AuditActor(run.metadata.actor_id, "application"), source=run.metadata.source, payload=_json_safe(payload), correlation_id=run.correlation_id, symbol=run.symbol, configuration_version=version)

    def health(self) -> dict[str, Any]:
        return {"status": self.registry.health()["status"], "registry": self.registry.health(), "execution_enabled": False, "plugins": len(self.infrastructure.plugins.registrations), "feature_flags": len(self.infrastructure.feature_flags.snapshot())}

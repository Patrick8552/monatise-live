from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from math import isfinite
from numbers import Real
from threading import RLock
from time import perf_counter
from typing import Any, AsyncIterator, Awaitable, Callable
from uuid import uuid4

from monatise.infrastructure.observability.models import (
    HealthCheck,
    HealthStatus,
    ExportResult,
    LogLevel,
    MetricPoint,
    MetricType,
    MetricSummary,
    SpanRecord,
    StructuredLog,
    freeze_observation_value,
)


HealthCallable = Callable[[], Awaitable[tuple[HealthStatus, str]]]
ExporterCallable = Callable[[dict[str, Any]], Awaitable[None]]


class ObservabilityManager:
    """In-process structured observability service.

    Production deployments may export these records to OpenTelemetry,
    Prometheus, Grafana, Sentry, ELK, or another backend.
    """

    def __init__(
        self,
        *,
        maximum_records_per_type: int = 10_000,
        maximum_metric_series: int = 1_000,
        health_check_timeout_seconds: float = 5.0,
        exporter_timeout_seconds: float = 10.0,
        sensitive_keys: tuple[str, ...] = (
            "api_key", "apikey", "secret", "token", "password",
            "private_key", "authorization",
        ),
    ) -> None:
        if (
            isinstance(maximum_records_per_type, bool)
            or not isinstance(maximum_records_per_type, int)
            or maximum_records_per_type < 1
        ):
            raise ValueError("maximum_records_per_type must be positive")
        if (
            isinstance(maximum_metric_series, bool)
            or not isinstance(maximum_metric_series, int)
            or maximum_metric_series < 1
        ):
            raise ValueError("maximum_metric_series must be positive")
        if (
            not isinstance(health_check_timeout_seconds, Real)
            or isinstance(health_check_timeout_seconds, bool)
            or not isfinite(float(health_check_timeout_seconds))
            or health_check_timeout_seconds <= 0
        ):
            raise ValueError("health_check_timeout_seconds must be finite and positive")
        if not isinstance(sensitive_keys, tuple) or any(
            not isinstance(key, str) or not key.strip()
            for key in sensitive_keys
        ):
            raise ValueError("sensitive_keys must contain non-empty strings")
        if (
            not isinstance(exporter_timeout_seconds, Real)
            or isinstance(exporter_timeout_seconds, bool)
            or not isfinite(float(exporter_timeout_seconds))
            or exporter_timeout_seconds <= 0
        ):
            raise ValueError("exporter_timeout_seconds must be finite and positive")
        self._logs: list[StructuredLog] = []
        self._metrics: list[MetricPoint] = []
        self._spans: list[SpanRecord] = []
        self._health_checks: dict[str, HealthCallable] = {}
        self._latest_health: dict[str, HealthCheck] = {}
        self._exporters: dict[str, ExporterCallable] = {}
        self._lock = asyncio.Lock()
        self._health_lock = RLock()
        self._maximum_records = maximum_records_per_type
        self._maximum_metric_series = maximum_metric_series
        self._metric_series: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
        self._metric_types: dict[str, MetricType] = {}
        self._health_check_timeout = float(health_check_timeout_seconds)
        self._exporter_timeout = float(exporter_timeout_seconds)
        self._sensitive_keys = {
            "".join(char for char in key.casefold() if char.isalnum())
            for key in sensitive_keys
        }

    async def log(
        self,
        level: LogLevel,
        message: str,
        *,
        source: str,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        symbol: str | None = None,
        fields: dict[str, Any] | None = None,
    ) -> StructuredLog:
        if not isinstance(level, LogLevel):
            raise ValueError("log level is invalid")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("log message is required")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("log source is required")
        if fields is not None and not isinstance(fields, dict):
            raise ValueError("log fields must be a dictionary")
        for value, field_name in (
            (correlation_id, "correlation_id"),
            (causation_id, "causation_id"),
            (symbol, "symbol"),
        ):
            if value is not None and (
                not isinstance(value, str) or not value.strip()
            ):
                raise ValueError(f"{field_name} must be a non-empty string")

        record = StructuredLog(
            timestamp=datetime.now(timezone.utc),
            level=level,
            message=message,
            source=source,
            correlation_id=correlation_id,
            causation_id=causation_id,
            symbol=symbol,
            fields=freeze_observation_value(
                self._redact(deepcopy(fields or {}))
            ),
        )
        async with self._lock:
            self._append_bounded(self._logs, record)
        return deepcopy(record)

    async def counter(
        self,
        name: str,
        value: float = 1.0,
        *,
        labels: dict[str, str] | None = None,
    ) -> MetricPoint:
        self._validate_metric_value(value)
        if value < 0:
            raise ValueError("counter increments cannot be negative")
        return await self._metric(
            name,
            MetricType.COUNTER,
            value,
            labels,
        )

    async def gauge(
        self,
        name: str,
        value: float,
        *,
        labels: dict[str, str] | None = None,
    ) -> MetricPoint:
        self._validate_metric_value(value)
        return await self._metric(
            name,
            MetricType.GAUGE,
            value,
            labels,
        )

    async def histogram(
        self,
        name: str,
        value: float,
        *,
        labels: dict[str, str] | None = None,
    ) -> MetricPoint:
        self._validate_metric_value(value)
        if value < 0:
            raise ValueError("histogram values cannot be negative")
        return await self._metric(
            name,
            MetricType.HISTOGRAM,
            value,
            labels,
        )

    async def _metric(
        self,
        name: str,
        metric_type: MetricType,
        value: float,
        labels: dict[str, str] | None,
    ) -> MetricPoint:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("metric name is required")
        if labels is not None and not isinstance(labels, dict):
            raise ValueError("metric labels must be a dictionary")
        safe_labels = dict(labels or {})
        if any(
            not isinstance(key, str) or not key.strip()
            or not isinstance(value, str)
            for key, value in safe_labels.items()
        ):
            raise ValueError("metric labels must use non-empty string keys and string values")

        point = MetricPoint(
            name=name,
            metric_type=metric_type,
            value=float(value),
            timestamp=datetime.now(timezone.utc),
            labels=freeze_observation_value(safe_labels),
        )
        async with self._lock:
            existing_type = self._metric_types.get(name)
            if existing_type is not None and existing_type is not metric_type:
                raise ValueError("metric name cannot be reused with a different type")
            self._metric_types[name] = metric_type
            series = (name, tuple(sorted(safe_labels.items())))
            if series not in self._metric_series:
                if len(self._metric_series) >= self._maximum_metric_series:
                    raise ValueError("maximum metric-series cardinality exceeded")
                self._metric_series.add(series)
            self._append_bounded(self._metrics, point)
        return deepcopy(point)

    @asynccontextmanager
    async def trace(
        self,
        name: str,
        *,
        source: str,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
        correlation_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, str]]:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("span name is required")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("span source is required")
        if attributes is not None and not isinstance(attributes, dict):
            raise ValueError("span attributes must be a dictionary")
        for value, field_name in (
            (trace_id, "trace_id"),
            (parent_span_id, "parent_span_id"),
            (correlation_id, "correlation_id"),
        ):
            if value is not None and (
                not isinstance(value, str) or not value.strip()
            ):
                raise ValueError(f"{field_name} must be a non-empty string")

        started_at = datetime.now(timezone.utc)
        started = perf_counter()
        actual_trace_id = trace_id or str(uuid4())
        span_id = str(uuid4())
        success = True
        error = None

        try:
            yield {
                "trace_id": actual_trace_id,
                "span_id": span_id,
            }
        except BaseException as exc:
            success = False
            error = type(exc).__name__
            raise
        finally:
            finished_at = datetime.now(timezone.utc)
            duration_ms = (perf_counter() - started) * 1000
            span = SpanRecord(
                trace_id=actual_trace_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
                name=name,
                source=source,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=duration_ms,
                success=success,
                correlation_id=correlation_id,
                attributes=freeze_observation_value(
                    self._redact(deepcopy(attributes or {}))
                ),
                error=error,
            )
            async with self._lock:
                self._append_bounded(self._spans, span)
                self._append_internal_metric_unlocked(MetricPoint(
                        name="operation.duration_ms",
                        metric_type=MetricType.HISTOGRAM,
                        value=duration_ms,
                        timestamp=finished_at,
                        labels=freeze_observation_value({
                            "operation": name,
                            "source": source,
                            "success": str(success).lower(),
                        }),
                    ))
                if not success:
                    self._append_internal_metric_unlocked(MetricPoint(
                            name="operation.errors_total",
                            metric_type=MetricType.COUNTER,
                            value=1.0,
                            timestamp=finished_at,
                            labels=freeze_observation_value({
                                "operation": name,
                                "source": source,
                            }),
                        ))

    def register_health_check(
        self,
        name: str,
        check: HealthCallable,
        *,
        replace: bool = False,
    ) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("health-check name is required")
        if not callable(check):
            raise ValueError("health check must be callable")
        with self._health_lock:
            if name in self._health_checks and not replace:
                raise ValueError(f"health check already registered: {name}")
            self._health_checks[name] = check

    async def run_health_checks(self) -> tuple[HealthCheck, ...]:
        with self._health_lock:
            checks = tuple(sorted(self._health_checks.items()))

        async def run_one(name: str, check: HealthCallable) -> HealthCheck:
            started = perf_counter()
            try:
                status, message = await asyncio.wait_for(
                    check(),
                    timeout=self._health_check_timeout,
                )
                if not isinstance(status, HealthStatus):
                    raise TypeError("health check must return HealthStatus")
                if not isinstance(message, str):
                    raise TypeError("health-check message must be a string")
            except Exception as exc:
                status = HealthStatus.UNHEALTHY
                message = type(exc).__name__

            latency_ms = (perf_counter() - started) * 1000
            return HealthCheck(
                    name=name,
                    status=status,
                    checked_at=datetime.now(timezone.utc),
                    message=message,
                    latency_ms=latency_ms,
                    metadata=freeze_observation_value({}),
                )

        results = tuple(await asyncio.gather(*(
            run_one(name, check) for name, check in checks
        )))
        with self._health_lock:
            self._latest_health.update({item.name: item for item in results})
        return results

    def unregister_health_check(self, name: str) -> None:
        with self._health_lock:
            self._health_checks.pop(name, None)
            self._latest_health.pop(name, None)

    def register_exporter(
        self,
        name: str,
        exporter: ExporterCallable,
        *,
        replace: bool = False,
    ) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("exporter name is required")
        if not callable(exporter):
            raise ValueError("exporter must be callable")
        with self._health_lock:
            if name in self._exporters and not replace:
                raise ValueError(f"exporter already registered: {name}")
            self._exporters[name] = exporter

    def unregister_exporter(self, name: str) -> None:
        with self._health_lock:
            self._exporters.pop(name, None)

    async def export(self) -> tuple[ExportResult, ...]:
        snapshot = await self.snapshot()
        with self._health_lock:
            exporters = tuple(sorted(self._exporters.items()))

        async def run_one(name: str, exporter: ExporterCallable) -> ExportResult:
            try:
                await asyncio.wait_for(
                    exporter(snapshot),
                    timeout=self._exporter_timeout,
                )
                success = True
                error = None
            except Exception as exc:
                success = False
                error = type(exc).__name__
            return ExportResult(
                exporter_name=name,
                success=success,
                exported_at=datetime.now(timezone.utc),
                error=error,
            )

        return tuple(await asyncio.gather(*(
            run_one(name, exporter) for name, exporter in exporters
        )))

    async def logs(
        self,
        *,
        level: LogLevel | None = None,
        source: str | None = None,
        correlation_id: str | None = None,
    ) -> tuple[StructuredLog, ...]:
        async with self._lock:
            records = [
                item for item in self._logs
                if (level is None or item.level is level)
                and (source is None or item.source == source)
                and (
                    correlation_id is None
                    or item.correlation_id == correlation_id
                )
            ]
            return tuple(deepcopy(records))

    async def metrics(
        self,
        *,
        name: str | None = None,
    ) -> tuple[MetricPoint, ...]:
        async with self._lock:
            records = [
                item for item in self._metrics
                if name is None or item.name == name
            ]
            return tuple(deepcopy(records))

    async def metric_summary(
        self,
        name: str,
        *,
        labels: dict[str, str] | None = None,
    ) -> MetricSummary | None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("metric name is required")
        expected_labels = dict(labels or {})
        if any(
            not isinstance(key, str) or not key.strip()
            or not isinstance(value, str)
            for key, value in expected_labels.items()
        ):
            raise ValueError("metric labels must use non-empty string keys and string values")
        async with self._lock:
            points = [
                point for point in self._metrics
                if point.name == name
                and all(point.labels.get(key) == value for key, value in expected_labels.items())
            ]
            if not points:
                return None
            values = [point.value for point in points]
            return MetricSummary(
                name=name,
                metric_type=points[0].metric_type,
                count=len(points),
                total=sum(values),
                minimum=min(values),
                maximum=max(values),
                latest=values[-1],
                labels=freeze_observation_value(expected_labels),
            )

    async def spans(
        self,
        *,
        trace_id: str | None = None,
        source: str | None = None,
    ) -> tuple[SpanRecord, ...]:
        async with self._lock:
            records = [
                item for item in self._spans
                if (trace_id is None or item.trace_id == trace_id)
                and (source is None or item.source == source)
            ]
            return tuple(deepcopy(records))

    async def snapshot(self) -> dict[str, Any]:
        with self._health_lock:
            health_check_names = tuple(sorted(self._health_checks))
            latest_health = tuple(
                deepcopy(self._latest_health[name])
                for name in sorted(self._latest_health)
            )
            exporter_names = tuple(sorted(self._exporters))
        async with self._lock:
            return freeze_observation_value({
                "logs": tuple(deepcopy(self._logs)),
                "metrics": tuple(deepcopy(self._metrics)),
                "spans": tuple(deepcopy(self._spans)),
                "health_check_names": health_check_names,
                "health_checks": latest_health,
                "exporter_names": exporter_names,
                "metadata": freeze_observation_value({
                    "read_only_snapshot": True,
                    "execution_enabled": False,
                    "production_exporters_replaceable": True,
                }),
            })

    def _append_bounded(self, target: list[Any], value: Any) -> None:
        target.append(value)
        excess = len(target) - self._maximum_records
        if excess > 0:
            del target[:excess]

    def _append_internal_metric_unlocked(self, point: MetricPoint) -> None:
        existing_type = self._metric_types.get(point.name)
        if existing_type is not None and existing_type is not point.metric_type:
            return
        self._metric_types[point.name] = point.metric_type
        series = (point.name, tuple(sorted(point.labels.items())))
        if series not in self._metric_series:
            if len(self._metric_series) >= self._maximum_metric_series:
                return
            self._metric_series.add(series)
        self._append_bounded(self._metrics, point)

    @staticmethod
    def _validate_metric_value(value: float) -> None:
        if (
            isinstance(value, bool)
            or not isinstance(value, Real)
            or not isfinite(float(value))
        ):
            raise ValueError("metric value must be a finite number")

    def _redact(
        self,
        value: Any,
        active: set[int] | None = None,
        depth: int = 0,
    ) -> Any:
        if depth > 100:
            raise ValueError("observability fields exceed maximum nesting depth")
        seen = active if active is not None else set()
        if isinstance(value, dict):
            identity = id(value)
            if identity in seen:
                raise ValueError("observability fields cannot contain reference cycles")
            seen.add(identity)
            try:
                return {
                    key: (
                        "***REDACTED***"
                        if isinstance(key, str) and self._is_sensitive_key(key)
                        else self._redact(item, seen, depth + 1)
                    )
                    for key, item in value.items()
                }
            finally:
                seen.remove(identity)
        if isinstance(value, list):
            identity = id(value)
            if identity in seen:
                raise ValueError("observability fields cannot contain reference cycles")
            seen.add(identity)
            try:
                return [self._redact(item, seen, depth + 1) for item in value]
            finally:
                seen.remove(identity)
        if isinstance(value, tuple):
            return tuple(self._redact(item, seen, depth + 1) for item in value)
        return value

    def _is_sensitive_key(self, key: str) -> bool:
        normalized = "".join(char for char in key.casefold() if char.isalnum())
        return normalized in self._sensitive_keys or normalized.endswith(
            ("secret", "token", "password", "privatekey", "authorization")
        )

    @property
    def execution_enabled(self) -> bool:
        return False

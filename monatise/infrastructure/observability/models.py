from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class FrozenDict(dict):
    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("observability record is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable

    def __deepcopy__(self, memo: dict[int, Any]) -> "FrozenDict":
        return self


def freeze_observation_value(value: Any) -> Any:
    if isinstance(value, dict):
        return FrozenDict({
            key: freeze_observation_value(item)
            for key, item in value.items()
        })
    if isinstance(value, (list, tuple)):
        return tuple(freeze_observation_value(item) for item in value)
    return value


class LogLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class MetricType(StrEnum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class StructuredLog:
    timestamp: datetime
    level: LogLevel
    message: str
    source: str
    correlation_id: str | None = None
    causation_id: str | None = None
    symbol: str | None = None
    fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MetricPoint:
    name: str
    metric_type: MetricType
    value: float
    timestamp: datetime
    labels: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SpanRecord:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    source: str
    started_at: datetime
    finished_at: datetime
    duration_ms: float
    success: bool
    correlation_id: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class HealthCheck:
    name: str
    status: HealthStatus
    checked_at: datetime
    message: str
    latency_ms: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MetricSummary:
    name: str
    metric_type: MetricType
    count: int
    total: float
    minimum: float
    maximum: float
    latest: float
    labels: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ExportResult:
    exporter_name: str
    success: bool
    exported_at: datetime
    error: str | None = None

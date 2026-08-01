from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from monatise.engines.execution_policy.models import ExecutionPolicyResult
from monatise.engines.reporting_intelligence.models import ReportResult


class IntegrationChannel(StrEnum):
    COINGLASS = "coinglass"
    TELEGRAM = "telegram"
    OPENCLAW = "openclaw"
    DATABASE = "database"
    DASHBOARD = "dashboard"
    AUDIT_LOG = "audit_log"


class IntegrationAction(StrEnum):
    INGEST = "ingest"
    PUBLISH = "publish"
    STORE = "store"
    SCHEDULE = "schedule"
    VALIDATE = "validate"


class IntegrationStatus(StrEnum):
    READY = "ready"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True)
class IntegrationEvent:
    event_id: str
    channel: IntegrationChannel
    action: IntegrationAction
    payload: dict[str, Any]
    created_at: datetime
    idempotency_key: str
    correlation_id: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.event_id.strip():
            raise ValueError("event_id is required")
        if not self.idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        if not self.correlation_id.strip():
            raise ValueError("correlation_id is required")


@dataclass(frozen=True)
class IntegrationRequest:
    report: ReportResult
    execution_policy: ExecutionPolicyResult
    requested_channels: tuple[IntegrationChannel, ...]
    generated_at: datetime

    enable_coinglass: bool = True
    enable_telegram: bool = True
    enable_openclaw: bool = True
    enable_database: bool = True
    enable_dashboard: bool = True
    enable_audit_log: bool = True
    allow_execution_adapter: bool = False

    def validate(self) -> None:
        if self.report.symbol != self.execution_policy.symbol:
            raise ValueError("report and execution-policy symbols must match")
        if not self.requested_channels:
            raise ValueError("at least one integration channel is required")
        if self.allow_execution_adapter:
            raise ValueError("execution adapters are outside Integration Engine scope")


@dataclass(frozen=True)
class IntegrationResult:
    symbol: str
    status: IntegrationStatus
    events: tuple[IntegrationEvent, ...]
    blocked_channels: tuple[IntegrationChannel, ...]
    reasons: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def execution_adapter_enabled(self) -> bool:
        return False

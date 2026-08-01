from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite
from numbers import Real
from typing import Any


class FeatureFlagState(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"


class FeatureFlagError(RuntimeError):
    pass


@dataclass(frozen=True)
class EvaluationContext:
    environment: str
    user_id: str | None = None
    symbol: str | None = None
    correlation_id: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not isinstance(self.environment, str) or not self.environment.strip():
            raise ValueError("evaluation environment is required")
        if self.environment != self.environment.strip():
            raise ValueError("evaluation environment cannot have surrounding whitespace")
        for value, name in (
            (self.user_id, "user_id"),
            (self.symbol, "symbol"),
            (self.correlation_id, "correlation_id"),
        ):
            if value is not None and (
                not isinstance(value, str) or not value.strip()
            ):
                raise ValueError(f"{name} must be a non-empty string")
            if value is not None and value != value.strip():
                raise ValueError(f"{name} cannot have surrounding whitespace")
        if not isinstance(self.attributes, dict):
            raise ValueError("context attributes must be a dictionary")


@dataclass(frozen=True)
class RolloutRule:
    environments: tuple[str, ...] = ()
    users: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    required_attributes: dict[str, Any] = field(default_factory=dict)
    percentage: float | None = None

    def validate(self) -> None:
        if self.percentage is not None:
            if (
                isinstance(self.percentage, bool)
                or not isinstance(self.percentage, Real)
                or not isfinite(float(self.percentage))
                or not 0 <= self.percentage <= 100
            ):
                raise ValueError("percentage must be finite and between 0 and 100")
        for values, name in (
            (self.environments, "environments"),
            (self.users, "users"),
            (self.symbols, "symbols"),
        ):
            if any(not isinstance(item, str) or not item.strip() for item in values):
                raise ValueError(f"{name} must contain non-empty strings")
            if any(item != item.strip() for item in values):
                raise ValueError(f"{name} cannot contain surrounding whitespace")
        if not isinstance(self.required_attributes, dict):
            raise ValueError("required_attributes must be a dictionary")
        if any(not isinstance(key, str) or not key.strip() for key in self.required_attributes):
            raise ValueError("required attribute names must be non-empty strings")


@dataclass(frozen=True)
class FeatureFlag:
    name: str
    state: FeatureFlagState
    default_value: bool
    rules: tuple[RolloutRule, ...] = ()
    immutable: bool = False
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not isinstance(self.name, str):
            raise ValueError("feature flag name must be a string")
        if not self.name.strip():
            raise ValueError("feature flag name is required")
        if self.name != self.name.strip():
            raise ValueError("feature flag name cannot have surrounding whitespace")
        if not isinstance(self.state, FeatureFlagState):
            raise ValueError("feature flag state is invalid")
        if not isinstance(self.default_value, bool):
            raise ValueError("default_value must be boolean")
        if not isinstance(self.immutable, bool):
            raise ValueError("immutable must be boolean")
        if not isinstance(self.rules, tuple):
            raise ValueError("feature flag rules must be a tuple")
        if not isinstance(self.metadata, dict):
            raise ValueError("feature flag metadata must be a dictionary")
        if self.description is not None and not isinstance(self.description, str):
            raise ValueError("feature flag description must be a string")
        for rule in self.rules:
            if not isinstance(rule, RolloutRule):
                raise ValueError("feature flag rules must be RolloutRule values")
            rule.validate()


@dataclass(frozen=True)
class FeatureFlagResult:
    name: str
    enabled: bool
    matched_rule_index: int | None
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

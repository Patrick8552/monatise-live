from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class ConfigLayer(StrEnum):
    DEFAULTS = "defaults"
    FILE = "file"
    ENVIRONMENT = "environment"
    RUNTIME = "runtime"


class ConfigError(RuntimeError):
    pass


class FrozenConfigError(ConfigError):
    pass


@dataclass(frozen=True)
class ConfigSnapshot:
    environment: Environment
    values: dict[str, Any]
    sources: dict[str, ConfigLayer]
    frozen: bool
    version: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def require(self, key: str) -> Any:
        if key not in self.values:
            raise ConfigError(f"required configuration key is missing: {key}")
        return self.values[key]

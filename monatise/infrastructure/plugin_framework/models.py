from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import re
from typing import Any, Protocol


class PluginState(StrEnum):
    DISCOVERED = "discovered"
    VALIDATED = "validated"
    LOADED = "loaded"
    STARTED = "started"
    STOPPED = "stopped"
    FAILED = "failed"
    DISABLED = "disabled"


class PluginCapability(StrEnum):
    MARKET_DATA = "market_data"
    REPORTING = "reporting"
    NOTIFICATION = "notification"
    STORAGE = "storage"
    SCHEDULING = "scheduling"
    OBSERVABILITY = "observability"
    ANALYTICS = "analytics"


class PluginError(RuntimeError):
    pass


SEMANTIC_VERSION_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


def validate_semantic_version(version: str) -> None:
    if not isinstance(version, str) or not SEMANTIC_VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"invalid semantic version: {version}")


@dataclass(frozen=True)
class PluginDependency:
    plugin_name: str
    minimum_version: str | None = None

    def validate(self) -> None:
        if not self.plugin_name.strip():
            raise ValueError("plugin_name is required")
        if self.minimum_version is not None:
            validate_semantic_version(self.minimum_version)


@dataclass(frozen=True)
class PluginManifest:
    name: str
    version: str
    entrypoint: str
    api_version: int
    capabilities: tuple[PluginCapability, ...]
    dependencies: tuple[PluginDependency, ...] = ()
    enabled_by_default: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("plugin name is required")
        validate_semantic_version(self.version)
        module_name, separator, object_name = self.entrypoint.partition(":")
        if (
            separator != ":"
            or not module_name
            or not object_name
            or ":" in object_name
            or any(not part.isidentifier() for part in module_name.split("."))
            or not object_name.isidentifier()
        ):
            raise ValueError("entrypoint must use 'module:object' format")
        if self.api_version < 1:
            raise ValueError("api_version must be positive")
        if any(not isinstance(item, PluginCapability) for item in self.capabilities):
            raise ValueError("plugin capabilities must use PluginCapability values")
        for dependency in self.dependencies:
            dependency.validate()
        dependency_names = [item.plugin_name for item in self.dependencies]
        if len(dependency_names) != len(set(dependency_names)):
            raise ValueError("plugin dependencies must be unique")
        if self.name in dependency_names:
            raise ValueError("plugin cannot depend on itself")


@dataclass(frozen=True)
class PluginContext:
    container: Any
    event_bus: Any
    configuration: Any
    metadata: dict[str, Any] = field(default_factory=dict)


class PluginLifecycle(Protocol):
    manifest: PluginManifest

    def register(self, context: PluginContext) -> None:
        ...

    async def start(self, context: PluginContext) -> None:
        ...

    async def stop(self, context: PluginContext) -> None:
        ...


@dataclass
class PluginRegistration:
    manifest: PluginManifest
    plugin: PluginLifecycle
    state: PluginState = PluginState.DISCOVERED
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

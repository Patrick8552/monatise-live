from __future__ import annotations

import asyncio
import importlib
from collections import defaultdict
from copy import deepcopy
from dataclasses import replace
from typing import Any

from monatise.infrastructure.plugin_framework.models import (
    PluginCapability,
    PluginContext,
    PluginError,
    PluginLifecycle,
    PluginManifest,
    PluginRegistration,
    PluginState,
    SEMANTIC_VERSION_PATTERN,
)


class PluginManager:
    """Loads approved plugins through explicit manifests and lifecycle hooks.

    Plugins may register adapters and services only. They cannot enable
    execution, override governance, mutate immutable configuration, or bypass
    the canonical engine pipeline.
    """

    def __init__(
        self,
        *,
        context: PluginContext,
        supported_api_version: int = 1,
        allowed_capabilities: tuple[PluginCapability, ...] = tuple(
            PluginCapability
        ),
    ) -> None:
        if supported_api_version < 1:
            raise ValueError("supported_api_version must be positive")
        if any(
            not isinstance(item, PluginCapability)
            for item in allowed_capabilities
        ):
            raise ValueError(
                "allowed_capabilities must use PluginCapability values"
            )

        self._context = context
        self._supported_api_version = supported_api_version
        self._allowed_capabilities = set(allowed_capabilities)
        self._plugins: dict[str, PluginRegistration] = {}
        self._lifecycle_locks: dict[str, asyncio.Lock] = {}
        self._disabled_from: dict[str, PluginState] = {}

    def add(self, plugin: PluginLifecycle) -> PluginRegistration:
        manifest = getattr(plugin, "manifest", None)
        if not isinstance(manifest, PluginManifest):
            raise PluginError("plugin must expose a PluginManifest")
        try:
            manifest.validate()
        except (TypeError, ValueError) as exc:
            raise PluginError(f"invalid plugin manifest: {exc}") from exc
        for hook in ("register", "start", "stop"):
            if not callable(getattr(plugin, hook, None)):
                raise PluginError(f"plugin lifecycle hook is missing: {hook}")

        if manifest.name in self._plugins:
            raise PluginError(
                f"plugin already registered: {manifest.name}"
            )

        registration = PluginRegistration(
            manifest=manifest,
            plugin=plugin,
            state=PluginState.DISCOVERED,
        )
        self._plugins[manifest.name] = registration
        self._lifecycle_locks[manifest.name] = asyncio.Lock()
        return self._copy_registration(registration)

    def discover_entrypoint(
        self,
        manifest: PluginManifest,
    ) -> PluginRegistration:
        try:
            manifest.validate()
        except (TypeError, ValueError) as exc:
            raise PluginError(f"invalid plugin manifest: {exc}") from exc

        try:
            module_name, object_name = manifest.entrypoint.split(":", 1)
        except ValueError as exc:
            raise PluginError(
                "entrypoint must use 'module:object' format"
            ) from exc

        try:
            module = importlib.import_module(module_name)
            plugin_object = getattr(module, object_name)
            plugin = plugin_object() if isinstance(plugin_object, type) else plugin_object
        except Exception as exc:
            raise PluginError(
                f"failed to import plugin {manifest.name}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        if getattr(plugin, "manifest", None) != manifest:
            raise PluginError(
                f"plugin manifest mismatch for {manifest.name}"
            )

        return self.add(plugin)

    def validate(self, name: str) -> PluginRegistration:
        return self._copy_registration(self._validate(name))

    def _validate(self, name: str) -> PluginRegistration:
        registration = self._require(name)
        manifest = registration.manifest

        if manifest.api_version != self._supported_api_version:
            registration.state = PluginState.FAILED
            registration.error = (
                f"unsupported plugin API version {manifest.api_version}; "
                f"expected {self._supported_api_version}"
            )
            raise PluginError(registration.error)

        forbidden = set(manifest.capabilities) - self._allowed_capabilities
        if forbidden:
            registration.state = PluginState.FAILED
            registration.error = (
                "plugin requests forbidden capabilities: "
                + ", ".join(sorted(item.value for item in forbidden))
            )
            raise PluginError(registration.error)

        for dependency in manifest.dependencies:
            dependency_registration = self._plugins.get(
                dependency.plugin_name
            )
            if dependency_registration is None:
                registration.state = PluginState.FAILED
                registration.error = (
                    f"missing plugin dependency: {dependency.plugin_name}"
                )
                raise PluginError(registration.error)

            if dependency.minimum_version is not None:
                if self._version_tuple(
                    dependency_registration.manifest.version
                ) < self._version_tuple(dependency.minimum_version):
                    registration.state = PluginState.FAILED
                    registration.error = (
                        f"plugin dependency {dependency.plugin_name} "
                        f"requires version >= {dependency.minimum_version}"
                    )
                    raise PluginError(registration.error)

        if registration.state in {
            PluginState.DISCOVERED,
            PluginState.VALIDATED,
            PluginState.FAILED,
        }:
            registration.state = PluginState.VALIDATED
        registration.error = None
        return registration

    def load(self, name: str) -> PluginRegistration:
        registration = self._require(name)
        if registration.state not in {
            PluginState.DISCOVERED,
            PluginState.VALIDATED,
        }:
            raise PluginError(
                f"plugin cannot load from state {registration.state.value}"
            )
        registration = self._validate(name)

        try:
            registration.plugin.register(self._context)
        except Exception as exc:
            registration.state = PluginState.FAILED
            registration.error = (
                f"plugin registration failed: {type(exc).__name__}: {exc}"
            )
            raise PluginError(registration.error) from exc

        registration.state = PluginState.LOADED
        return self._copy_registration(registration)

    async def start(self, name: str) -> PluginRegistration:
        self._require(name)
        async with self._lifecycle_locks[name]:
            return await self._start_locked(name)

    async def _start_locked(self, name: str) -> PluginRegistration:
        registration = self._require(name)

        if registration.state is PluginState.STARTED:
            return self._copy_registration(registration)

        for dependency in registration.manifest.dependencies:
            dependency_registration = self._require(dependency.plugin_name)
            if dependency_registration.state is not PluginState.STARTED:
                raise PluginError(
                    f"plugin dependency is not started: {dependency.plugin_name}"
                )

        if registration.state is PluginState.DISCOVERED:
            self.load(name)
        elif registration.state is PluginState.VALIDATED:
            self.load(name)

        if registration.state not in {
            PluginState.LOADED,
            PluginState.STOPPED,
        }:
            raise PluginError(
                f"plugin cannot start from state {registration.state.value}"
            )

        try:
            await registration.plugin.start(self._context)
        except Exception as exc:
            registration.state = PluginState.FAILED
            registration.error = (
                f"plugin start failed: {type(exc).__name__}: {exc}"
            )
            raise PluginError(registration.error) from exc

        registration.state = PluginState.STARTED
        registration.error = None
        return self._copy_registration(registration)

    async def stop(self, name: str) -> PluginRegistration:
        self._require(name)
        async with self._lifecycle_locks[name]:
            return await self._stop_locked(name)

    async def _stop_locked(self, name: str) -> PluginRegistration:
        registration = self._require(name)

        if registration.state is not PluginState.STARTED:
            raise PluginError(
                f"plugin cannot stop from state {registration.state.value}"
            )

        active_dependents = self._started_dependents(name)
        if active_dependents:
            raise PluginError(
                f"plugin cannot stop while dependents are started: "
                + ", ".join(active_dependents)
            )

        try:
            await registration.plugin.stop(self._context)
        except Exception as exc:
            registration.state = PluginState.FAILED
            registration.error = (
                f"plugin stop failed: {type(exc).__name__}: {exc}"
            )
            raise PluginError(registration.error) from exc

        registration.state = PluginState.STOPPED
        return self._copy_registration(registration)

    def disable(self, name: str) -> PluginRegistration:
        registration = self._require(name)
        if registration.state is PluginState.STARTED:
            raise PluginError("started plugin must be stopped before disabling")
        active_dependents = self._started_dependents(name)
        if active_dependents:
            raise PluginError(
                f"plugin cannot be disabled while dependents are started: "
                + ", ".join(active_dependents)
            )
        if registration.state is PluginState.DISABLED:
            return self._copy_registration(registration)
        self._disabled_from[name] = registration.state
        registration.state = PluginState.DISABLED
        return self._copy_registration(registration)

    def enable(self, name: str) -> PluginRegistration:
        registration = self._require(name)
        if registration.state is not PluginState.DISABLED:
            raise PluginError(
                f"plugin cannot be enabled from state {registration.state.value}"
            )
        registration.state = self._disabled_from.pop(
            name,
            PluginState.DISCOVERED,
        )
        registration.error = None
        return self._copy_registration(registration)

    async def start_all(self) -> tuple[PluginRegistration, ...]:
        ordered = self._dependency_order()
        results: list[PluginRegistration] = []
        started_here: list[str] = []
        try:
            for name in ordered:
                registration = self._plugins[name]
                if registration.state is PluginState.DISABLED:
                    continue
                if registration.state is PluginState.STARTED:
                    continue
                if not registration.manifest.enabled_by_default:
                    continue
                self._validate(name)
                unavailable = [
                    dependency.plugin_name
                    for dependency in registration.manifest.dependencies
                    if self._plugins[dependency.plugin_name].state
                    is not PluginState.STARTED
                ]
                if unavailable:
                    raise PluginError(
                        f"enabled plugin {name} has unavailable dependencies: "
                        + ", ".join(unavailable)
                    )
                results.append(await self.start(name))
                started_here.append(name)
        except Exception as exc:
            rollback_errors: list[str] = []
            for started_name in reversed(started_here):
                try:
                    await self.stop(started_name)
                except PluginError as rollback_exc:
                    rollback_errors.append(str(rollback_exc))
            suffix = (
                "; rollback failures: " + "; ".join(rollback_errors)
                if rollback_errors
                else ""
            )
            raise PluginError(f"plugin startup transaction failed: {exc}{suffix}") from exc
        return tuple(results)

    async def stop_all(self) -> tuple[PluginRegistration, ...]:
        ordered = list(reversed(self._dependency_order()))
        results = []
        for name in ordered:
            registration = self._plugins[name]
            if registration.state is PluginState.STARTED:
                results.append(await self.stop(name))
        return tuple(results)

    def _dependency_order(self) -> tuple[str, ...]:
        graph: dict[str, set[str]] = defaultdict(set)
        indegree: dict[str, int] = {
            name: 0 for name in self._plugins
        }

        for name, registration in self._plugins.items():
            for dependency in registration.manifest.dependencies:
                if dependency.plugin_name not in self._plugins:
                    continue
                graph[dependency.plugin_name].add(name)
                indegree[name] += 1

        queue = sorted(
            name for name, degree in indegree.items()
            if degree == 0
        )
        ordered: list[str] = []

        while queue:
            current = queue.pop(0)
            ordered.append(current)

            for dependent in sorted(graph[current]):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    queue.append(dependent)
                    queue.sort()

        if len(ordered) != len(self._plugins):
            raise PluginError("circular plugin dependency detected")

        return tuple(ordered)

    def _require(self, name: str) -> PluginRegistration:
        registration = self._plugins.get(name)
        if registration is None:
            raise PluginError(f"plugin is not registered: {name}")
        return registration

    def _started_dependents(self, name: str) -> tuple[str, ...]:
        return tuple(sorted(
            candidate_name
            for candidate_name, registration in self._plugins.items()
            if registration.state is PluginState.STARTED
            and any(
                dependency.plugin_name == name
                for dependency in registration.manifest.dependencies
            )
        ))

    @staticmethod
    def _copy_registration(
        registration: PluginRegistration,
    ) -> PluginRegistration:
        return replace(
            registration,
            metadata=deepcopy(registration.metadata),
        )

    @staticmethod
    def _version_tuple(version: str) -> tuple[int, ...]:
        match = SEMANTIC_VERSION_PATTERN.fullmatch(version)
        if match is None:
            raise PluginError(f"invalid semantic version: {version}")
        major, minor, patch, prerelease = match.groups()
        # Stable releases sort after prereleases of the same core version.
        prerelease_rank = 1 if prerelease is None else 0
        prerelease_parts = () if prerelease is None else tuple(
            (0, int(part)) if part.isdigit() else (1, part)
            for part in prerelease.split(".")
        )
        return (int(major), int(minor), int(patch), prerelease_rank, prerelease_parts)

    @property
    def registrations(self) -> tuple[PluginRegistration, ...]:
        return tuple(
            self._copy_registration(registration)
            for registration in self._plugins.values()
        )

    @property
    def execution_capability_available(self) -> bool:
        return False

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from threading import RLock, local
from typing import Any, Hashable, Iterator

from monatise.infrastructure.dependency_injection.models import (
    DependencyResolutionError,
    Lifetime,
    Registration,
    Resolver,
    Scope,
)


class Container(Resolver):
    """Thread-safe dependency injection container.

    The container manages application composition only. It contains no trading
    logic, engine decisions, exchange credentials, or execution capability.
    """

    def __init__(self) -> None:
        self._registrations: dict[Hashable, Registration] = {}
        self._singletons: dict[Hashable, Any] = {}
        self._lock = RLock()
        self._context = local()

    def register(
        self,
        key: Hashable,
        factory,
        *,
        lifetime: Lifetime = Lifetime.TRANSIENT,
        dependencies: tuple[Hashable, ...] = (),
        metadata: dict[str, Any] | None = None,
        replace: bool = False,
    ) -> None:
        registration = Registration(
            key=key,
            factory=factory,
            lifetime=lifetime,
            dependencies=dependencies,
            metadata=deepcopy(metadata or {}),
        )
        registration.validate()

        with self._lock:
            if key in self._registrations and not replace:
                raise ValueError(f"dependency already registered: {key!r}")
            replaced = self._singletons.pop(key, None) if replace else None
            self._registrations[key] = registration
            if replaced is not None:
                self._dispose_instance(replaced)

    def register_instance(
        self,
        key: Hashable,
        instance: Any,
        *,
        replace: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.register(
            key,
            lambda _: instance,
            lifetime=Lifetime.SINGLETON,
            metadata=metadata,
            replace=replace,
        )
        with self._lock:
            self._singletons[key] = instance

    def resolve(self, key: Hashable) -> Any:
        with self._lock:
            registration = self._registrations.get(key)
            if registration is None:
                raise DependencyResolutionError(
                    f"dependency is not registered: {key!r}"
                )

            resolution_stack = self._current_resolution_stack()
            if key in resolution_stack:
                cycle = " -> ".join(
                    repr(item)
                    for item in (*resolution_stack, key)
                )
                raise DependencyResolutionError(
                    f"circular dependency detected: {cycle}"
                )

            if registration.lifetime is Lifetime.SINGLETON:
                if key in self._singletons:
                    return self._singletons[key]

            if registration.lifetime is Lifetime.SCOPED:
                active_scope = self._current_scope()
                if active_scope is None:
                    raise DependencyResolutionError(
                        f"scoped dependency requires an active scope: {key!r}"
                    )
                active_scope.validate_active()
                if key in active_scope.instances:
                    return active_scope.instances[key]

            resolution_stack.append(key)
            try:
                for dependency in registration.dependencies:
                    self.resolve(dependency)
                instance = registration.factory(self)
            except DependencyResolutionError:
                raise
            except Exception as exc:
                raise DependencyResolutionError(
                    f"failed to construct dependency {key!r}: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
            finally:
                resolution_stack.pop()

            if registration.lifetime is Lifetime.SINGLETON:
                self._singletons[key] = instance
            elif registration.lifetime is Lifetime.SCOPED:
                active_scope = self._current_scope()
                assert active_scope is not None
                active_scope.instances[key] = instance

            return instance

    def resolve_all(self, keys: tuple[Hashable, ...]) -> tuple[Any, ...]:
        return tuple(self.resolve(key) for key in keys)

    def validate_graph(self) -> tuple[str, ...]:
        errors: list[str] = []

        with self._lock:
            for key, registration in self._registrations.items():
                for dependency in registration.dependencies:
                    if dependency not in self._registrations:
                        errors.append(
                            f"{key!r} depends on unregistered {dependency!r}"
                        )

        for key in tuple(self._registrations):
            try:
                self._detect_cycle(key, ())
            except DependencyResolutionError as exc:
                errors.append(str(exc))

        return tuple(dict.fromkeys(errors))

    def _detect_cycle(
        self,
        key: Hashable,
        path: tuple[Hashable, ...],
    ) -> None:
        if key in path:
            cycle = " -> ".join(repr(item) for item in (*path, key))
            raise DependencyResolutionError(
                f"circular dependency detected: {cycle}"
            )

        registration = self._registrations.get(key)
        if registration is None:
            return

        for dependency in registration.dependencies:
            self._detect_cycle(dependency, (*path, key))

    @contextmanager
    def scope(self, name: str) -> Iterator[Scope]:
        if not name.strip():
            raise ValueError("scope name is required")

        with self._lock:
            if self._current_scope() is not None:
                raise DependencyResolutionError(
                    "nested scopes are not supported"
                )
            scope = Scope(name=name)
            self._context.active_scope = scope

        try:
            yield scope
        finally:
            with self._lock:
                scope.dispose()
                self._context.active_scope = None

    def contains(self, key: Hashable) -> bool:
        with self._lock:
            return key in self._registrations

    def unregister(self, key: Hashable) -> None:
        with self._lock:
            self._registrations.pop(key, None)
            instance = self._singletons.pop(key, None)
            if instance is not None:
                self._dispose_instance(instance)

    def clear(self) -> None:
        with self._lock:
            self._registrations.clear()
            singletons = tuple(reversed(tuple(self._singletons.values())))
            self._singletons.clear()
            active_scope = self._current_scope()
            if active_scope is not None:
                active_scope.dispose()
                self._context.active_scope = None
            self._dispose_many(singletons)

    @staticmethod
    def _dispose_instance(instance: Any) -> None:
        callback = getattr(instance, "dispose", None)
        if not callable(callback):
            callback = getattr(instance, "close", None)
        if callable(callback):
            callback()

    @classmethod
    def _dispose_many(cls, instances: tuple[Any, ...]) -> None:
        failures: list[str] = []
        for instance in instances:
            try:
                cls._dispose_instance(instance)
            except Exception as exc:
                failures.append(f"{type(exc).__name__}: {exc}")
        if failures:
            raise DependencyResolutionError(
                "dependency disposal failed: " + "; ".join(failures)
            )

    def _current_scope(self) -> Scope | None:
        return getattr(self._context, "active_scope", None)

    def _current_resolution_stack(self) -> list[Hashable]:
        stack = getattr(self._context, "resolution_stack", None)
        if stack is None:
            stack = []
            self._context.resolution_stack = stack
        return stack

    @property
    def registrations(self) -> tuple[Registration, ...]:
        with self._lock:
            return tuple(self._registrations.values())

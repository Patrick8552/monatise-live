from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, Hashable


class Lifetime(StrEnum):
    SINGLETON = "singleton"
    TRANSIENT = "transient"
    SCOPED = "scoped"


class DependencyResolutionError(RuntimeError):
    pass


Factory = Callable[["Resolver"], Any]


class Resolver:
    def resolve(self, key: Hashable) -> Any:
        raise NotImplementedError


@dataclass(frozen=True)
class Registration:
    key: Hashable
    factory: Factory
    lifetime: Lifetime
    dependencies: tuple[Hashable, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.key is None:
            raise ValueError("registration key is required")
        if not callable(self.factory):
            raise ValueError("registration factory must be callable")


@dataclass
class Scope:
    name: str
    instances: dict[Hashable, Any] = field(default_factory=dict)
    disposed: bool = False

    def validate_active(self) -> None:
        if self.disposed:
            raise DependencyResolutionError(
                f"scope '{self.name}' has already been disposed"
            )

    def dispose(self) -> None:
        failures: list[str] = []
        try:
            for instance in reversed(tuple(self.instances.values())):
                callback = getattr(instance, "dispose", None)
                if not callable(callback):
                    callback = getattr(instance, "close", None)
                if callable(callback):
                    try:
                        callback()
                    except Exception as exc:
                        failures.append(f"{type(exc).__name__}: {exc}")
        finally:
            self.instances.clear()
            self.disposed = True
        if failures:
            raise DependencyResolutionError(
                "scope disposal failed: " + "; ".join(failures)
            )

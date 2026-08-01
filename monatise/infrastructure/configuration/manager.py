from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any, Callable

from monatise.infrastructure.configuration.models import (
    ConfigError,
    ConfigLayer,
    ConfigSnapshot,
    Environment,
    FrozenConfigError,
)


Validator = Callable[[Any], None]


_LAYER_PRIORITY = {
    ConfigLayer.DEFAULTS: 0,
    ConfigLayer.FILE: 1,
    ConfigLayer.ENVIRONMENT: 2,
    ConfigLayer.RUNTIME: 3,
}


class ConfigurationManager:
    """Layered, validated, and freezable configuration manager.

    Priority order:
    defaults < file < environment < runtime

    Hard invariants cannot be overridden at runtime.
    """

    def __init__(
        self,
        *,
        environment: Environment = Environment.DEVELOPMENT,
        env_prefix: str = "MONATISE_",
    ) -> None:
        self._environment = environment
        self._env_prefix = env_prefix
        self._values: dict[str, Any] = {}
        self._sources: dict[str, ConfigLayer] = {}
        self._validators: dict[str, Validator] = {}
        self._required: set[str] = set()
        self._immutable_keys: set[str] = set()
        self._frozen = False
        self._version = 0
        self._lock = RLock()

    def register_validator(
        self,
        key: str,
        validator: Validator,
        *,
        required: bool = False,
        immutable: bool = False,
    ) -> None:
        if not key.strip():
            raise ValueError("configuration key is required")
        if not callable(validator):
            raise ValueError("validator must be callable")

        with self._lock:
            if self._frozen:
                raise FrozenConfigError(
                    "configuration is frozen and cannot be modified"
                )
            self._validators[key] = validator
            if required:
                self._required.add(key)
            if immutable:
                self._immutable_keys.add(key)

    def load_defaults(self, values: dict[str, Any]) -> None:
        self._merge(values, ConfigLayer.DEFAULTS)

    def load_file(self, path: str | Path) -> None:
        file_path = Path(path)
        if not file_path.exists():
            raise ConfigError(f"configuration file not found: {file_path}")

        try:
            if file_path.suffix.lower() == ".json":
                data = json.loads(file_path.read_text(encoding="utf-8"))
            else:
                raise ConfigError(
                    "only JSON configuration files are supported in this layer"
                )
        except json.JSONDecodeError as exc:
            raise ConfigError(
                f"invalid JSON configuration: {exc}"
            ) from exc

        if not isinstance(data, dict):
            raise ConfigError("configuration file root must be an object")

        self._merge(data, ConfigLayer.FILE)

    def load_environment(self, environ: dict[str, str] | None = None) -> None:
        source = environ if environ is not None else dict(os.environ)
        parsed: dict[str, Any] = {}

        for raw_key, raw_value in source.items():
            if not raw_key.startswith(self._env_prefix):
                continue
            key = raw_key[len(self._env_prefix):].lower().replace("__", ".")
            parsed[key] = self._parse_scalar(raw_value)

        self._merge(parsed, ConfigLayer.ENVIRONMENT)

    def apply_runtime_overrides(self, values: dict[str, Any]) -> None:
        with self._lock:
            if self._frozen:
                raise FrozenConfigError(
                    "configuration is frozen and cannot accept runtime overrides"
                )

            forbidden = self._immutable_keys.intersection(values)
            if forbidden:
                names = ", ".join(sorted(forbidden))
                raise ConfigError(
                    f"immutable configuration keys cannot be overridden: {names}"
                )

        self._merge(values, ConfigLayer.RUNTIME)

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []

        with self._lock:
            for key in sorted(self._required):
                if key not in self._values:
                    errors.append(f"required configuration key is missing: {key}")

            for key, validator in self._validators.items():
                if key not in self._values:
                    continue
                try:
                    validator(self._values[key])
                except Exception as exc:
                    errors.append(
                        f"{key}: {type(exc).__name__}: {exc}"
                    )

        return tuple(errors)

    def freeze(self) -> ConfigSnapshot:
        with self._lock:
            if self._frozen:
                return self.snapshot()
            errors = self.validate()
            if errors:
                raise ConfigError(
                    "configuration validation failed: " + "; ".join(errors)
                )
            self._frozen = True
            self._version += 1
            return self.snapshot()

    def snapshot(self) -> ConfigSnapshot:
        with self._lock:
            return ConfigSnapshot(
                environment=self._environment,
                values=deepcopy(self._values),
                sources=dict(self._sources),
                frozen=self._frozen,
                version=self._version,
                metadata={
                    "env_prefix": self._env_prefix,
                    "immutable_keys": tuple(sorted(self._immutable_keys)),
                    "required_keys": tuple(sorted(self._required)),
                    "runtime_execution_override_allowed": False,
                },
            )

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return deepcopy(self._values.get(key, default))

    def require(self, key: str) -> Any:
        with self._lock:
            if key not in self._values:
                raise ConfigError(
                    f"required configuration key is missing: {key}"
                )
            return deepcopy(self._values[key])

    def source_of(self, key: str) -> ConfigLayer | None:
        with self._lock:
            return self._sources.get(key)

    def _merge(
        self,
        values: dict[str, Any],
        layer: ConfigLayer,
    ) -> None:
        if not isinstance(values, dict):
            raise ValueError("configuration values must be a dictionary")

        flattened = self._flatten(values)

        with self._lock:
            if self._frozen:
                raise FrozenConfigError(
                    "configuration is frozen and cannot be modified"
                )

            applicable = {
                key: deepcopy(value)
                for key, value in flattened.items()
                if self._sources.get(key) is None
                or _LAYER_PRIORITY[layer]
                >= _LAYER_PRIORITY[self._sources[key]]
            }

            # Validate the complete candidate change before committing any key.
            # This keeps a rejected layer from leaving partial configuration.
            for key, value in applicable.items():
                if (
                    key in self._immutable_keys
                    and key in self._values
                    and self._values[key] != value
                ):
                    raise ConfigError(
                        f"immutable configuration key cannot change: {key}"
                    )

                validator = self._validators.get(key)
                if validator is not None:
                    try:
                        validator(value)
                    except Exception as exc:
                        raise ConfigError(
                            f"invalid configuration for {key}: {exc}"
                        ) from exc

            for key, value in applicable.items():
                self._values[key] = value
                self._sources[key] = layer

    @classmethod
    def _flatten(
        cls,
        values: dict[str, Any],
        prefix: str = "",
    ) -> dict[str, Any]:
        flattened: dict[str, Any] = {}
        for key, value in values.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("configuration keys must be non-empty strings")
            if key != key.strip():
                raise ValueError("configuration keys cannot have surrounding whitespace")
            full_key = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, dict):
                flattened.update(cls._flatten(value, full_key))
            else:
                flattened[full_key] = value
        return flattened

    @staticmethod
    def _parse_scalar(value: str) -> Any:
        stripped = value.strip()
        lowered = stripped.lower()

        if lowered in {"true", "false"}:
            return lowered == "true"
        if lowered in {"none", "null"}:
            return None

        try:
            return int(stripped)
        except ValueError:
            pass

        try:
            return float(stripped)
        except ValueError:
            pass

        if (
            (stripped.startswith("[") and stripped.endswith("]"))
            or (stripped.startswith("{") and stripped.endswith("}"))
        ):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                pass

        return stripped

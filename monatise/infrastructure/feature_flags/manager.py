from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from json import dumps
from threading import RLock

from monatise.infrastructure.feature_flags.models import (
    EvaluationContext,
    FeatureFlag,
    FeatureFlagError,
    FeatureFlagResult,
    FeatureFlagState,
    RolloutRule,
)


class FeatureFlagManager:
    """Evaluates controlled feature rollouts with immutable safety flags.

    Feature flags may control product behavior, experiments, and integrations.
    They may not enable capabilities prohibited by code.
    """

    _SAFETY_FLAGS = {
        "autonomous_execution": False,
        "execution_adapter_submission": False,
        "governance_kill_switch": True,
        "audit_logging": True,
    }

    def __init__(self) -> None:
        self._flags: dict[str, FeatureFlag] = {}
        self._lock = RLock()

    def register(
        self,
        flag: FeatureFlag,
        *,
        replace: bool = False,
    ) -> None:
        flag.validate()
        self._validate_safety_flag(flag)
        flag = deepcopy(flag)

        with self._lock:
            existing = self._flags.get(flag.name)
            if existing is not None and not replace:
                raise FeatureFlagError(
                    f"feature flag already exists: {flag.name}"
                )
            if existing is not None and existing.immutable:
                raise FeatureFlagError(
                    f"immutable feature flag cannot be replaced: {flag.name}"
                )

            self._flags[flag.name] = flag

    def evaluate(
        self,
        name: str,
        context: EvaluationContext,
    ) -> FeatureFlagResult:
        if not isinstance(context, EvaluationContext):
            raise ValueError("context must be an EvaluationContext")
        context = deepcopy(context)
        context.validate()
        with self._lock:
            flag = deepcopy(self._flags.get(name))

        if flag is None:
            raise FeatureFlagError(
                f"feature flag is not registered: {name}"
            )

        if flag.state is FeatureFlagState.DISABLED:
            return FeatureFlagResult(
                name=name,
                enabled=False,
                matched_rule_index=None,
                reason="feature flag is globally disabled",
                metadata={"immutable": flag.immutable},
            )

        for index, rule in enumerate(flag.rules):
            if self._matches(rule, context, name):
                return FeatureFlagResult(
                    name=name,
                    enabled=True,
                    matched_rule_index=index,
                    reason=f"matched rollout rule {index}",
                    metadata={
                        "immutable": flag.immutable,
                        "default_value": flag.default_value,
                    },
                )

        return FeatureFlagResult(
            name=name,
            enabled=flag.default_value,
            matched_rule_index=None,
            reason="no rollout rule matched; default applied",
            metadata={
                "immutable": flag.immutable,
                "default_value": flag.default_value,
            },
        )

    def set_state(
        self,
        name: str,
        state: FeatureFlagState,
    ) -> None:
        if not isinstance(state, FeatureFlagState):
            raise ValueError("feature flag state is invalid")
        with self._lock:
            flag = self._require(name)
            if flag.immutable:
                raise FeatureFlagError(
                    f"immutable feature flag cannot change state: {name}"
                )
            self._flags[name] = FeatureFlag(
                name=flag.name,
                state=state,
                default_value=flag.default_value,
                rules=flag.rules,
                immutable=flag.immutable,
                description=flag.description,
                metadata=deepcopy(flag.metadata),
            )

    def update_rules(
        self,
        name: str,
        rules: tuple[RolloutRule, ...],
    ) -> None:
        if not isinstance(rules, tuple):
            raise ValueError("rules must be a tuple")
        for rule in rules:
            if not isinstance(rule, RolloutRule):
                raise ValueError("rules must contain RolloutRule values")
            rule.validate()
        rules = deepcopy(rules)

        with self._lock:
            flag = self._require(name)
            if flag.immutable:
                raise FeatureFlagError(
                    f"immutable feature flag cannot change rules: {name}"
                )
            self._flags[name] = FeatureFlag(
                name=flag.name,
                state=flag.state,
                default_value=flag.default_value,
                rules=rules,
                immutable=flag.immutable,
                description=flag.description,
                metadata=deepcopy(flag.metadata),
            )

    def snapshot(self) -> tuple[FeatureFlag, ...]:
        with self._lock:
            return tuple(
                deepcopy(self._flags[name])
                for name in sorted(self._flags)
            )

    def _require(self, name: str) -> FeatureFlag:
        flag = self._flags.get(name)
        if flag is None:
            raise FeatureFlagError(
                f"feature flag is not registered: {name}"
            )
        return flag

    @staticmethod
    def _matches(
        rule: RolloutRule,
        context: EvaluationContext,
        flag_name: str,
    ) -> bool:
        if (
            rule.environments
            and context.environment.casefold()
            not in {item.casefold() for item in rule.environments}
        ):
            return False

        if rule.users:
            if context.user_id is None or context.user_id not in rule.users:
                return False

        if rule.symbols:
            symbol = (context.symbol or "").upper()
            allowed = {item.upper() for item in rule.symbols}
            if symbol not in allowed:
                return False

        for key, expected in rule.required_attributes.items():
            if context.attributes.get(key) != expected:
                return False

        if rule.percentage is not None:
            subject = (
                context.user_id
                or context.correlation_id
                or ((context.symbol or "").upper() or None)
                or context.environment.casefold()
            )
            bucket = FeatureFlagManager._bucket(
                flag_name,
                subject,
            )
            if bucket >= rule.percentage:
                return False

        return True

    @staticmethod
    def _bucket(flag_name: str, subject: str) -> float:
        digest = sha256(
            dumps([flag_name, subject], separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        integer = int(digest[:8], 16)
        return (integer / 2**32) * 100

    @classmethod
    def _validate_safety_flag(cls, flag: FeatureFlag) -> None:
        required = cls._SAFETY_FLAGS.get(flag.name)
        if required is None:
            return
        expected_state = (
            FeatureFlagState.ENABLED
            if required
            else FeatureFlagState.DISABLED
        )
        if (
            not flag.immutable
            or flag.state is not expected_state
            or flag.default_value is not required
            or flag.rules
        ):
            raise FeatureFlagError(
                f"safety feature flag has immutable required value: "
                f"{flag.name}={required}"
            )

    @property
    def runtime_execution_enablement_allowed(self) -> bool:
        return False

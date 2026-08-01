from monatise.infrastructure.feature_flags import (
    EvaluationContext,
    FeatureFlag,
    FeatureFlagError,
    FeatureFlagManager,
    FeatureFlagState,
    RolloutRule,
)


def test_default_value_is_used_without_matching_rules() -> None:
    manager = FeatureFlagManager()
    manager.register(
        FeatureFlag(
            name="new_reporting",
            state=FeatureFlagState.ENABLED,
            default_value=False,
        )
    )

    result = manager.evaluate(
        "new_reporting",
        EvaluationContext(environment="production"),
    )

    assert result.enabled is False


def test_environment_and_symbol_rule() -> None:
    manager = FeatureFlagManager()
    manager.register(
        FeatureFlag(
            name="btc_order_flow_v2",
            state=FeatureFlagState.ENABLED,
            default_value=False,
            rules=(
                RolloutRule(
                    environments=("staging",),
                    symbols=("BTCUSDT",),
                ),
            ),
        )
    )

    enabled = manager.evaluate(
        "btc_order_flow_v2",
        EvaluationContext(
            environment="staging",
            symbol="BTCUSDT",
        ),
    )
    disabled = manager.evaluate(
        "btc_order_flow_v2",
        EvaluationContext(
            environment="production",
            symbol="BTCUSDT",
        ),
    )

    assert enabled.enabled is True
    assert disabled.enabled is False


def test_percentage_rollout_is_deterministic() -> None:
    manager = FeatureFlagManager()
    manager.register(
        FeatureFlag(
            name="experiment",
            state=FeatureFlagState.ENABLED,
            default_value=False,
            rules=(RolloutRule(percentage=50),),
        )
    )

    context = EvaluationContext(
        environment="test",
        user_id="user-123",
    )

    first = manager.evaluate("experiment", context)
    second = manager.evaluate("experiment", context)

    assert first.enabled == second.enabled
    assert first.matched_rule_index == second.matched_rule_index


def test_global_disable_overrides_rules() -> None:
    manager = FeatureFlagManager()
    manager.register(
        FeatureFlag(
            name="dashboard",
            state=FeatureFlagState.DISABLED,
            default_value=True,
            rules=(RolloutRule(environments=("production",)),),
        )
    )

    result = manager.evaluate(
        "dashboard",
        EvaluationContext(environment="production"),
    )

    assert result.enabled is False


def test_immutable_flag_cannot_change() -> None:
    manager = FeatureFlagManager()
    manager.register(
        FeatureFlag(
            name="autonomous_execution",
            state=FeatureFlagState.DISABLED,
            default_value=False,
            immutable=True,
        )
    )

    try:
        manager.set_state(
            "autonomous_execution",
            FeatureFlagState.ENABLED,
        )
    except FeatureFlagError as exc:
        assert "immutable" in str(exc)
    else:
        raise AssertionError("expected immutable flag error")


def test_attribute_rule() -> None:
    manager = FeatureFlagManager()
    manager.register(
        FeatureFlag(
            name="premium_dashboard",
            state=FeatureFlagState.ENABLED,
            default_value=False,
            rules=(
                RolloutRule(
                    required_attributes={"tier": "premium"},
                ),
            ),
        )
    )

    result = manager.evaluate(
        "premium_dashboard",
        EvaluationContext(
            environment="production",
            attributes={"tier": "premium"},
        ),
    )

    assert result.enabled is True


def test_manager_cannot_enable_execution_at_runtime() -> None:
    manager = FeatureFlagManager()

    assert manager.runtime_execution_enablement_allowed is False
    assert not hasattr(manager, "place_order")
    assert not hasattr(manager, "submit_trade")


def test_prohibited_safety_flag_cannot_be_registered_enabled() -> None:
    manager = FeatureFlagManager()
    try:
        manager.register(FeatureFlag(
            name="autonomous_execution",
            state=FeatureFlagState.ENABLED,
            default_value=True,
            immutable=True,
        ))
    except FeatureFlagError as exc:
        assert "immutable required value" in str(exc)
    else:
        raise AssertionError("expected execution safety invariant failure")


def test_required_positive_safety_flags_cannot_be_disabled() -> None:
    manager = FeatureFlagManager()
    for name in ("governance_kill_switch", "audit_logging"):
        try:
            manager.register(FeatureFlag(
                name=name,
                state=FeatureFlagState.DISABLED,
                default_value=False,
                immutable=True,
            ))
        except FeatureFlagError:
            pass
        else:
            raise AssertionError("expected positive safety invariant failure")


def test_registration_and_snapshot_are_mutation_isolated() -> None:
    manager = FeatureFlagManager()
    attributes = {"tier": "premium"}
    metadata = {"owner": {"team": "reporting"}}
    flag = FeatureFlag(
        name="isolated",
        state=FeatureFlagState.ENABLED,
        default_value=False,
        rules=(RolloutRule(required_attributes=attributes),),
        metadata=metadata,
    )
    manager.register(flag)
    attributes["tier"] = "free"
    metadata["owner"]["team"] = "mutated"

    result = manager.evaluate(
        "isolated",
        EvaluationContext(
            environment="production",
            attributes={"tier": "premium"},
        ),
    )
    assert result.enabled is True

    snapshot = manager.snapshot()
    snapshot[0].metadata["owner"]["team"] = "snapshot-mutation"
    assert manager.snapshot()[0].metadata["owner"]["team"] == "reporting"


def test_rollout_boundaries_and_environment_matching() -> None:
    manager = FeatureFlagManager()
    manager.register(FeatureFlag(
        name="always",
        state=FeatureFlagState.ENABLED,
        default_value=False,
        rules=(RolloutRule(environments=("PRODUCTION",), percentage=100),),
    ))
    manager.register(FeatureFlag(
        name="never",
        state=FeatureFlagState.ENABLED,
        default_value=False,
        rules=(RolloutRule(percentage=0),),
    ))
    context = EvaluationContext(environment="production", user_id="user")
    assert manager.evaluate("always", context).enabled is True
    assert manager.evaluate("never", context).enabled is False


def test_invalid_runtime_state_is_rejected() -> None:
    manager = FeatureFlagManager()
    manager.register(FeatureFlag(
        name="dashboard",
        state=FeatureFlagState.DISABLED,
        default_value=False,
    ))
    try:
        manager.set_state("dashboard", "enabled")
    except ValueError as exc:
        assert "state is invalid" in str(exc)
    else:
        raise AssertionError("expected invalid state failure")

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from monatise.infrastructure.configuration import (
    ConfigError,
    ConfigLayer,
    ConfigurationManager,
    Environment,
    FrozenConfigError,
)


def positive(value):
    if value <= 0:
        raise ValueError("must be positive")


def test_layer_precedence() -> None:
    manager = ConfigurationManager()
    manager.load_defaults({"risk": {"max": 1}})
    manager.load_environment({"MONATISE_RISK__MAX": "2"})
    manager.apply_runtime_overrides({"risk.max": 3})

    assert manager.get("risk.max") == 3
    assert manager.source_of("risk.max") is ConfigLayer.RUNTIME


def test_layer_precedence_is_independent_of_load_order() -> None:
    manager = ConfigurationManager()
    manager.apply_runtime_overrides({"risk.max": 3})
    manager.load_environment({"MONATISE_RISK__MAX": "2"})
    manager.load_defaults({"risk": {"max": 1}})

    assert manager.get("risk.max") == 3
    assert manager.source_of("risk.max") is ConfigLayer.RUNTIME


def test_json_file_loading() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "config.json"
        path.write_text(
            json.dumps({"mode": "paper", "risk": {"max": 0.02}}),
            encoding="utf-8",
        )

        manager = ConfigurationManager()
        manager.load_file(path)

        assert manager.get("mode") == "paper"
        assert manager.get("risk.max") == 0.02


def test_environment_scalar_parsing() -> None:
    manager = ConfigurationManager()
    manager.load_environment(
        {
            "MONATISE_ENABLED": "true",
            "MONATISE_RETRIES": "3",
            "MONATISE_RATIO": "1.5",
            "IGNORED": "value",
        }
    )

    assert manager.get("enabled") is True
    assert manager.get("retries") == 3
    assert manager.get("ratio") == 1.5
    assert manager.get("ignored") is None


def test_required_and_validator_behavior() -> None:
    manager = ConfigurationManager()
    manager.register_validator(
        "scheduler.interval",
        positive,
        required=True,
    )
    manager.load_defaults({"scheduler": {"interval": 5}})

    assert manager.validate() == ()
    snapshot = manager.freeze()
    assert snapshot.frozen is True


def test_validation_failure_blocks_freeze() -> None:
    manager = ConfigurationManager()
    manager.register_validator(
        "scheduler.interval",
        positive,
        required=True,
    )

    try:
        manager.freeze()
    except ConfigError as exc:
        assert "validation failed" in str(exc)
    else:
        raise AssertionError("expected validation failure")


def test_immutable_key_cannot_change() -> None:
    manager = ConfigurationManager()
    manager.register_validator(
        "execution.autonomous_enabled",
        lambda value: (
            None if value is False
            else (_ for _ in ()).throw(
                ValueError("must remain false")
            )
        ),
        immutable=True,
    )
    manager.load_defaults(
        {"execution": {"autonomous_enabled": False}}
    )

    try:
        manager.apply_runtime_overrides(
            {"execution.autonomous_enabled": True}
        )
    except ConfigError as exc:
        assert "immutable" in str(exc)
    else:
        raise AssertionError("expected immutable-key error")


def test_frozen_configuration_rejects_changes() -> None:
    manager = ConfigurationManager(
        environment=Environment.PRODUCTION,
    )
    manager.load_defaults({"mode": "paper"})
    manager.freeze()

    try:
        manager.apply_runtime_overrides({"mode": "live"})
    except FrozenConfigError:
        pass
    else:
        raise AssertionError("expected frozen configuration error")


def test_snapshot_is_isolated_copy() -> None:
    manager = ConfigurationManager()
    manager.load_defaults({"nested": {"value": 1}})
    snapshot = manager.snapshot()
    snapshot.values["nested.value"] = 999

    assert manager.get("nested.value") == 1


def test_returned_mutable_value_cannot_modify_manager() -> None:
    manager = ConfigurationManager()
    manager.load_defaults({"symbols": ["BTC"]})

    symbols = manager.get("symbols")
    symbols.append("ETH")

    assert manager.get("symbols") == ["BTC"]


def test_rejected_layer_is_atomic() -> None:
    manager = ConfigurationManager()
    manager.register_validator("risk.max", positive)

    try:
        manager.load_defaults({"mode": "paper", "risk": {"max": 0}})
    except ConfigError:
        pass
    else:
        raise AssertionError("expected validation failure")

    assert manager.get("mode") is None


def test_manager_is_non_executable() -> None:
    manager = ConfigurationManager()

    assert not hasattr(manager, "place_order")
    assert not hasattr(manager, "submit_trade")


def test_freeze_is_idempotent() -> None:
    manager = ConfigurationManager()
    first = manager.freeze()
    second = manager.freeze()

    assert first.version == 1
    assert second.version == 1


def test_empty_or_ambiguous_configuration_keys_are_rejected() -> None:
    manager = ConfigurationManager()
    for values in ({"": 1}, {" key ": 1}):
        try:
            manager.load_defaults(values)
        except ValueError:
            pass
        else:
            raise AssertionError("expected invalid key rejection")

import os

from monatise.live.config import LIVE_CONFIRMATION, RuntimeConfig


def test_live_mode_requires_all_order_gates() -> None:
    config = RuntimeConfig(mode="live", account_address="0xabc", secret_key="secret")

    assert not config.live_enabled


def test_live_mode_enables_only_with_explicit_confirmation() -> None:
    config = RuntimeConfig(
        mode="live",
        allow_live_orders=True,
        live_confirmation=LIVE_CONFIRMATION,
        account_address="0xabc",
        secret_key="secret",
    )

    assert config.live_enabled


def test_order_size_cannot_exceed_max_order_notional() -> None:
    config = RuntimeConfig(order_quote_size=500, max_order_notional=100)

    try:
        config.validate()
    except ValueError as error:
        assert "max order notional" in str(error)
    else:
        raise AssertionError("expected invalid risk sizing to fail")


def test_global_hyperliquid_credentials_are_ignored_by_default() -> None:
    old_address = os.environ.get("HYPERLIQUID_ACCOUNT_ADDRESS")
    old_secret = os.environ.get("HYPERLIQUID_SECRET_KEY")
    old_enabled = os.environ.get("MONATISE_ENABLE_GLOBAL_CREDENTIALS")
    os.environ["HYPERLIQUID_ACCOUNT_ADDRESS"] = "0xglobal"
    os.environ["HYPERLIQUID_SECRET_KEY"] = "global-secret"
    os.environ.pop("MONATISE_ENABLE_GLOBAL_CREDENTIALS", None)
    try:
        config = RuntimeConfig.from_env()
        assert config.account_address == ""
        assert config.secret_key == ""
    finally:
        _restore_env("HYPERLIQUID_ACCOUNT_ADDRESS", old_address)
        _restore_env("HYPERLIQUID_SECRET_KEY", old_secret)
        _restore_env("MONATISE_ENABLE_GLOBAL_CREDENTIALS", old_enabled)


def _restore_env(key: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value

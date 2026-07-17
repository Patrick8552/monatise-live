import os

from monatise.live.config import LIVE_CONFIRMATION, RuntimeConfig


def test_live_mode_requires_all_order_gates() -> None:
    config = RuntimeConfig(mode="live", account_address="0xabc", secret_key="secret")

    assert not config.live_enabled


def test_live_mode_enables_only_with_explicit_confirmation() -> None:
    config = RuntimeConfig(
        mode="live",
        execution_mode="live",
        allow_live_orders=True,
        live_confirmation=LIVE_CONFIRMATION,
        account_address="0xabc",
        secret_key="secret",
    )

    assert config.live_enabled


def test_live_mode_dry_run_does_not_enable_order_placement() -> None:
    config = RuntimeConfig(
        mode="live",
        execution_mode="dry_run",
        allow_live_orders=True,
        live_confirmation=LIVE_CONFIRMATION,
        account_address="0xabc",
        secret_key="secret",
    )

    assert not config.live_enabled


def test_order_size_cannot_exceed_max_order_notional() -> None:
    config = RuntimeConfig(order_quote_size=500, max_order_notional=100)

    try:
        config.validate()
    except ValueError as error:
        assert "max order notional" in str(error)
    else:
        raise AssertionError("expected invalid risk sizing to fail")


def test_total_notional_defaults_to_trading_capital() -> None:
    config = RuntimeConfig(quote=25_000)

    assert config.max_total_notional == 25_000
    assert config.leverage == 10
    assert config.signal_session_window == "always"


def test_startup_lower_chart_interval_is_valid() -> None:
    config = RuntimeConfig(chart_interval="1m")

    config.validate()


def test_env_signal_window_defaults_to_always() -> None:
    old_window = os.environ.get("MONATISE_SIGNAL_SESSION_WINDOW")
    os.environ.pop("MONATISE_SIGNAL_SESSION_WINDOW", None)
    try:
        config = RuntimeConfig.from_env()
        assert config.signal_session_window == "always"
    finally:
        _restore_env("MONATISE_SIGNAL_SESSION_WINDOW", old_window)


def test_total_notional_env_override_is_respected() -> None:
    old_quote = os.environ.get("MONATISE_QUOTE")
    old_limit = os.environ.get("MONATISE_MAX_TOTAL_NOTIONAL")
    old_leverage = os.environ.get("MONATISE_LEVERAGE")
    os.environ["MONATISE_QUOTE"] = "25000"
    os.environ["MONATISE_MAX_TOTAL_NOTIONAL"] = "5000"
    os.environ["MONATISE_LEVERAGE"] = "10"
    try:
        config = RuntimeConfig.from_env()
        assert config.quote == 25_000
        assert config.max_total_notional == 5_000
        assert config.leverage == 10
    finally:
        _restore_env("MONATISE_QUOTE", old_quote)
        _restore_env("MONATISE_MAX_TOTAL_NOTIONAL", old_limit)
        _restore_env("MONATISE_LEVERAGE", old_leverage)


def test_leverage_must_be_positive() -> None:
    config = RuntimeConfig(leverage=0)

    try:
        config.validate()
    except ValueError as error:
        assert "LEVERAGE" in str(error)
    else:
        raise AssertionError("expected invalid leverage to fail")


def test_env_daily_loss_defaults_to_five_percent_of_quote() -> None:
    old_quote = os.environ.get("MONATISE_QUOTE")
    old_loss = os.environ.get("MONATISE_MAX_DAILY_LOSS")
    old_loss_pct = os.environ.get("MONATISE_MAX_DAILY_LOSS_PCT")
    os.environ["MONATISE_QUOTE"] = "25000"
    os.environ.pop("MONATISE_MAX_DAILY_LOSS", None)
    os.environ.pop("MONATISE_MAX_DAILY_LOSS_PCT", None)
    try:
        config = RuntimeConfig.from_env()
        assert config.max_daily_loss == 1_250
        assert config.max_daily_loss_pct == 0.05
    finally:
        _restore_env("MONATISE_QUOTE", old_quote)
        _restore_env("MONATISE_MAX_DAILY_LOSS", old_loss)
        _restore_env("MONATISE_MAX_DAILY_LOSS_PCT", old_loss_pct)


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


def test_data_feed_defaults_to_coinglass() -> None:
    old_feed = os.environ.get("MONATISE_DATA_FEED")
    os.environ.pop("MONATISE_DATA_FEED", None)
    try:
        config = RuntimeConfig.from_env()
        assert config.data_feed == "coinglass"
        config.validate()
    finally:
        _restore_env("MONATISE_DATA_FEED", old_feed)


def test_data_feed_keeps_coinglass_from_env() -> None:
    old_feed = os.environ.get("MONATISE_DATA_FEED")
    os.environ["MONATISE_DATA_FEED"] = "coinglass"
    try:
        config = RuntimeConfig.from_env()
        assert config.data_feed == "coinglass"
        config.validate()
    finally:
        _restore_env("MONATISE_DATA_FEED", old_feed)


def test_hyperliquid_data_feed_is_valid() -> None:
    config = RuntimeConfig(data_feed="hyperliquid")
    config.validate()


def _restore_env(key: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value

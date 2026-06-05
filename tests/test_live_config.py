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

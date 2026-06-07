from __future__ import annotations

import base64
import os
import tempfile

from monatise.live.users import UserCredentials, UserStore


def _with_key() -> str:
    key = base64.urlsafe_b64encode(b"0" * 32).decode("utf-8")
    old_key = os.environ.get("MONATISE_ENCRYPTION_KEY")
    os.environ["MONATISE_ENCRYPTION_KEY"] = key
    return old_key or ""


def _restore_key(old_key: str) -> None:
    if old_key:
        os.environ["MONATISE_ENCRYPTION_KEY"] = old_key
    else:
        os.environ.pop("MONATISE_ENCRYPTION_KEY", None)


def test_user_store_authenticates_and_loads_session_user() -> None:
    old_key = _with_key()
    try:
        with tempfile.NamedTemporaryFile() as db:
            store = UserStore(db.name)
            user = store.create_user("TraderOne", "password123")
            assert store.authenticate("traderone", "wrong") is None
            assert store.authenticate("traderone", "password123") == user
            token = store.create_session(user.id)
            assert store.user_for_session(token) == user
    finally:
        _restore_key(old_key)


def test_user_store_encrypts_credentials_per_user() -> None:
    old_key = _with_key()
    try:
        with tempfile.NamedTemporaryFile() as db:
            store = UserStore(db.name)
            user = store.create_user("trader-two", "password123")
            credentials = UserCredentials(account_address="0x1234567890abcdef", secret_key="secret")
            store.save_credentials(user.id, credentials)

            assert store.has_credentials(user.id)
            assert store.credentials_for_user(user.id) == credentials
    finally:
        _restore_key(old_key)


def test_user_store_saves_asset_and_free_access_settings() -> None:
    old_key = _with_key()
    try:
        with tempfile.NamedTemporaryFile() as db:
            store = UserStore(db.name)
            user = store.create_user("trader-three", "password123")

            assert store.settings_for_user(user.id).selected_symbol == "BTC"
            settings = store.save_selected_symbol(user.id, "eth")
            assert settings.selected_symbol == "ETH"
            settings = store.save_subscription_plan(user.id, "free")
            assert settings.subscription_plan == "free"
            assert settings.subscription_status == "active"
    finally:
        _restore_key(old_key)


def test_user_store_saves_one_minute_trading_rules_on_free_access() -> None:
    old_key = _with_key()
    try:
        with tempfile.NamedTemporaryFile() as db:
            store = UserStore(db.name)
            user = store.create_user("trader-four", "password123")

            settings = store.save_trading_rules(
                user.id,
                chart_interval="1m",
                london_commodity_only=False,
                max_daily_loss_pct=0.12,
                session_guard_minutes=15,
                stale_grid_cancel=False,
            )

            assert settings.chart_interval == "1m"
            assert settings.max_daily_loss_pct == 0.12
            assert settings.session_guard_minutes == 15
            assert not settings.stale_grid_cancel
            assert not settings.london_commodity_only
    finally:
        _restore_key(old_key)


def test_user_store_rejects_excessive_drawdown_limit() -> None:
    old_key = _with_key()
    try:
        with tempfile.NamedTemporaryFile() as db:
            store = UserStore(db.name)
            user = store.create_user("trader-five", "password123")

            try:
                store.save_trading_rules(
                    user.id,
                    chart_interval="1h",
                    london_commodity_only=True,
                    max_daily_loss_pct=0.25,
                    session_guard_minutes=60,
                    stale_grid_cancel=True,
                )
                raise AssertionError("expected excessive drawdown limit to fail")
            except ValueError as error:
                assert "drawdown limit" in str(error)
    finally:
        _restore_key(old_key)

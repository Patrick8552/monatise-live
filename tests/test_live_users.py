from __future__ import annotations

import base64
import os
import tempfile

import pytest

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


def test_user_store_remembers_last_profile_for_ip_without_password() -> None:
    old_key = _with_key()
    try:
        with tempfile.NamedTemporaryFile() as db:
            store = UserStore(db.name)
            user = store.create_user("remember@example.com", "password123")

            store.record_login(user.id, user.username, "203.0.113.10")
            hint = store.login_hint_for_ip("203.0.113.10")

            assert hint is not None
            assert hint.username == "remember@example.com"
            assert hint.last_login_at > 0
            assert hint.last_seen_at > 0
            assert store.login_hint_for_ip("203.0.113.11") is None
    finally:
        _restore_key(old_key)


def test_user_store_updates_last_seen_for_login_hint() -> None:
    old_key = _with_key()
    try:
        with tempfile.NamedTemporaryFile() as db:
            store = UserStore(db.name)
            user = store.create_user("seen@example.com", "password123")

            store.record_login(user.id, user.username, "203.0.113.12")
            original = store.login_hint_for_ip("203.0.113.12")
            store.touch_seen(user.id, user.username, "203.0.113.12")
            updated = store.login_hint_for_ip("203.0.113.12")

            assert original is not None
            assert updated is not None
            assert updated.username == "seen@example.com"
            assert updated.last_seen_at >= original.last_seen_at
            assert updated.last_login_at == original.last_login_at
    finally:
        _restore_key(old_key)


def test_user_store_resets_password_with_email_code() -> None:
    old_key = _with_key()
    try:
        with tempfile.NamedTemporaryFile() as db:
            store = UserStore(db.name)
            user = store.create_user("reset-user@example.com", "password123")
            reset = store.create_password_reset_code(user.username)
            token = store.create_session(user.id)

            assert reset is not None
            reset_user = store.reset_password_with_code("reset-user@example.com", reset.code, "newpass123")

            assert reset_user == user
            assert store.authenticate("reset-user@example.com", "password123") is None
            assert store.authenticate("reset-user@example.com", "newpass123") == user
            assert store.user_for_session(token) is None
            assert store.reset_password_with_code("reset-user@example.com", reset.code, "againpass123") is None
    finally:
        _restore_key(old_key)


def test_user_store_rejects_wrong_password_reset_code() -> None:
    old_key = _with_key()
    try:
        with tempfile.NamedTemporaryFile() as db:
            store = UserStore(db.name)
            user = store.create_user("reset-two@example.com", "password123")
            store.create_password_reset_code(user.username)

            assert store.reset_password_with_code("reset-two@example.com", "wrong", "newpass123") is None
            assert store.authenticate("reset-two@example.com", "password123") == user
    finally:
        _restore_key(old_key)


def test_user_store_authenticates_login_code_once() -> None:
    old_key = _with_key()
    try:
        with tempfile.NamedTemporaryFile() as db:
            store = UserStore(db.name)
            user = store.create_user("code-user@example.com", "password123")
            login_code = store.create_login_code(user.username)

            assert login_code is not None
            assert login_code.user == user
            assert store.authenticate_login_code("code-user@example.com", "wrong") is None
            assert store.authenticate_login_code("code-user@example.com", login_code.code) == user
            assert store.authenticate_login_code("code-user@example.com", login_code.code) is None
            assert store.authenticate("code-user@example.com", "password123") == user
    finally:
        _restore_key(old_key)


def test_user_store_returns_no_login_code_for_unknown_email() -> None:
    old_key = _with_key()
    try:
        with tempfile.NamedTemporaryFile() as db:
            store = UserStore(db.name)

            assert store.create_login_code("missing@example.com") is None
            assert store.authenticate_login_code("missing@example.com", "123456") is None
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
            settings = store.save_subscription_plan(user.id, "private", "trialing")
            assert settings.subscription_plan == "private"
            assert settings.subscription_status == "trialing"
    finally:
        _restore_key(old_key)


def test_user_store_saves_profile_name_across_settings_updates() -> None:
    old_key = _with_key()
    try:
        with tempfile.NamedTemporaryFile() as db:
            store = UserStore(db.name)
            user = store.create_user("named-trader@example.com", "password123")

            settings = store.save_client_name(user.id, "  Ada   Desk  ")
            assert settings.client_name == "Ada Desk"

            settings = store.save_selected_symbol(user.id, "eth")
            assert settings.selected_symbol == "ETH"
            assert settings.client_name == "Ada Desk"

            with pytest.raises(ValueError, match="crypto assets only"):
                store.save_selected_symbol(user.id, "gold")

            settings = store.save_trading_rules(
                user.id,
                chart_interval="1h",
                london_commodity_only=True,
                max_daily_loss_pct=0.05,
                session_guard_minutes=60,
                stale_grid_cancel=True,
            )
            assert settings.client_name == "Ada Desk"

            settings = store.save_subscription_plan(user.id, "private", "active")
            assert settings.client_name == "Ada Desk"
    finally:
        _restore_key(old_key)


def test_user_store_saves_spotify_playlist_across_settings_updates() -> None:
    old_key = _with_key()
    try:
        with tempfile.NamedTemporaryFile() as db:
            store = UserStore(db.name)
            user = store.create_user("playlist-trader@example.com", "password123")

            settings = store.save_spotify_playlist(user.id, "https://open.spotify.com/playlist/37i9dQZF1DX0XUsuxWHRQd")
            assert settings.spotify_playlist_url == "https://open.spotify.com/playlist/37i9dQZF1DX0XUsuxWHRQd"
            assert settings.spotify_playlist_embed_url == "https://open.spotify.com/embed/playlist/37i9dQZF1DX0XUsuxWHRQd"

            settings = store.save_selected_symbol(user.id, "eth")
            assert settings.spotify_playlist_embed_url.endswith("/37i9dQZF1DX0XUsuxWHRQd")

            settings = store.save_spotify_playlist(user.id, "")
            assert settings.spotify_playlist_url == ""
            assert settings.spotify_playlist_embed_url == ""
    finally:
        _restore_key(old_key)


def test_user_store_saves_startup_plan_trading_rules_on_free_access() -> None:
    old_key = _with_key()
    try:
        with tempfile.NamedTemporaryFile() as db:
            store = UserStore(db.name)
            user = store.create_user("trader-four", "password123")

            settings = store.save_trading_rules(
                user.id,
                chart_interval="30m",
                london_commodity_only=False,
                max_daily_loss_pct=0.12,
                session_guard_minutes=15,
                stale_grid_cancel=False,
            )

            assert settings.chart_interval == "30m"
            assert settings.leverage == 10
            assert settings.max_daily_loss_pct == 0.12
            assert settings.signal_session_window == "london_new_york"
            assert settings.session_guard_minutes == 15
            assert not settings.stale_grid_cancel
            assert not settings.london_commodity_only
    finally:
        _restore_key(old_key)


def test_user_store_saves_grid_sizing_rules() -> None:
    old_key = _with_key()
    try:
        with tempfile.NamedTemporaryFile() as db:
            store = UserStore(db.name)
            user = store.create_user("trader-six", "password123")

            settings = store.save_trading_rules(
                user.id,
                chart_interval="4h",
                signal_session_window="always",
                london_commodity_only=True,
                max_daily_loss_pct=0.05,
                session_guard_minutes=30,
                stale_grid_cancel=True,
                order_quote_size=40,
                max_total_notional=240,
                max_position_value=400,
            )

            assert settings.leverage == 10
            assert settings.signal_session_window == "always"
            assert settings.order_quote_size == 40
            assert settings.max_order_notional == 40
            assert settings.max_total_notional == 240
            assert settings.max_position_value == 400
    finally:
        _restore_key(old_key)


def test_user_store_rejects_order_size_above_total_open_grid() -> None:
    old_key = _with_key()
    try:
        with tempfile.NamedTemporaryFile() as db:
            store = UserStore(db.name)
            user = store.create_user("trader-seven", "password123")

            try:
                store.save_trading_rules(
                    user.id,
                    chart_interval="1h",
                    london_commodity_only=True,
                    max_daily_loss_pct=0.05,
                    session_guard_minutes=60,
                    stale_grid_cancel=True,
                    order_quote_size=250,
                    max_total_notional=100,
                    max_position_value=400,
                )
                raise AssertionError("expected invalid sizing to fail")
            except ValueError as error:
                assert "total open grid" in str(error)
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

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

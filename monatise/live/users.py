from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from monatise.live.secrets import secret_value


SESSION_SECONDS = 60 * 60 * 24 * 14


@dataclass(frozen=True)
class User:
    id: int
    username: str


@dataclass(frozen=True)
class UserCredentials:
    account_address: str
    secret_key: str


@dataclass(frozen=True)
class UserSettings:
    selected_symbol: str = "BTC"
    subscription_plan: str = "free"
    subscription_status: str = "active"


def default_auth_db_path() -> str:
    configured = os.getenv("MONATISE_AUTH_DB")
    if configured:
        return configured
    if Path("/data").exists():
        return "/data/monatise-users.db"
    return str(Path(__file__).resolve().parents[2] / "work" / "monatise-users.db")


def _hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 250_000)
    return salt, digest.hex()


def _fernet_key() -> bytes:
    configured = secret_value("MONATISE_ENCRYPTION_KEY", "")
    if configured:
        return configured.encode("utf-8")
    seed = secret_value("MONATISE_CONTROL_TOKEN", "") or "monatise-development-key"
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def encryption_key_configured() -> bool:
    return bool(secret_value("MONATISE_ENCRYPTION_KEY", ""))


class UserStore:
    def __init__(self, path: str | None = None) -> None:
        self.path = path or default_auth_db_path()
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._fernet = Fernet(_fernet_key())
        self._init_db()

    def create_user(self, username: str, password: str) -> User:
        username = username.strip().lower()
        self._validate_username_password(username, password)
        salt, digest = _hash_password(password)
        with self._connect() as conn:
            try:
                cursor = conn.execute(
                    "insert into users(username, password_salt, password_hash, created_at) values (?, ?, ?, ?)",
                    (username, salt, digest, time.time()),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError("username already exists") from error
        return User(id=int(cursor.lastrowid), username=username)

    def authenticate(self, username: str, password: str) -> User | None:
        username = username.strip().lower()
        with self._connect() as conn:
            row = conn.execute(
                "select id, username, password_salt, password_hash from users where username = ?",
                (username,),
            ).fetchone()
        if row is None:
            return None
        _, expected = _hash_password(password, row["password_salt"])
        if not hmac.compare_digest(expected, row["password_hash"]):
            return None
        return User(id=int(row["id"]), username=str(row["username"]))

    def create_session(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        with self._connect() as conn:
            conn.execute(
                "insert into sessions(token, user_id, expires_at) values (?, ?, ?)",
                (token, user_id, time.time() + SESSION_SECONDS),
            )
        return token

    def user_for_session(self, token: str) -> User | None:
        if not token:
            return None
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                """
                select users.id, users.username, sessions.expires_at
                from sessions
                join users on users.id = sessions.user_id
                where sessions.token = ?
                """,
                (token,),
            ).fetchone()
            conn.execute("delete from sessions where expires_at < ?", (now,))
        if row is None or float(row["expires_at"]) < now:
            return None
        return User(id=int(row["id"]), username=str(row["username"]))

    def delete_session(self, token: str) -> None:
        with self._connect() as conn:
            conn.execute("delete from sessions where token = ?", (token,))

    def save_credentials(self, user_id: int, credentials: UserCredentials) -> None:
        account_address = credentials.account_address.strip()
        secret_key = credentials.secret_key.strip()
        if not account_address.startswith("0x") or len(account_address) < 12:
            raise ValueError("enter the funded Hyperliquid account address")
        if not secret_key:
            raise ValueError("enter the API wallet secret key")
        encrypted_secret = self._fernet.encrypt(secret_key.encode("utf-8")).decode("utf-8")
        with self._connect() as conn:
            conn.execute(
                """
                insert into credentials(user_id, account_address, encrypted_secret_key, updated_at)
                values (?, ?, ?, ?)
                on conflict(user_id) do update set
                  account_address = excluded.account_address,
                  encrypted_secret_key = excluded.encrypted_secret_key,
                  updated_at = excluded.updated_at
                """,
                (user_id, account_address, encrypted_secret, time.time()),
            )

    def save_selected_symbol(self, user_id: int, symbol: str) -> UserSettings:
        settings = self.settings_for_user(user_id)
        selected_symbol = symbol.strip().upper()
        if not selected_symbol:
            raise ValueError("select an asset")
        with self._connect() as conn:
            conn.execute(
                """
                insert into user_settings(user_id, selected_symbol, subscription_plan, subscription_status, updated_at)
                values (?, ?, ?, ?, ?)
                on conflict(user_id) do update set
                  selected_symbol = excluded.selected_symbol,
                  updated_at = excluded.updated_at
                """,
                (user_id, selected_symbol, settings.subscription_plan, settings.subscription_status, time.time()),
            )
        return self.settings_for_user(user_id)

    def save_subscription_plan(self, user_id: int, plan: str) -> UserSettings:
        plan = plan.strip().lower()
        if plan not in {"free", "pro"}:
            raise ValueError("unknown subscription plan")
        settings = self.settings_for_user(user_id)
        with self._connect() as conn:
            conn.execute(
                """
                insert into user_settings(user_id, selected_symbol, subscription_plan, subscription_status, updated_at)
                values (?, ?, ?, ?, ?)
                on conflict(user_id) do update set
                  subscription_plan = excluded.subscription_plan,
                  subscription_status = excluded.subscription_status,
                  updated_at = excluded.updated_at
                """,
                (user_id, settings.selected_symbol, plan, "active", time.time()),
            )
        return self.settings_for_user(user_id)

    def settings_for_user(self, user_id: int) -> UserSettings:
        with self._connect() as conn:
            row = conn.execute(
                """
                select selected_symbol, subscription_plan, subscription_status
                from user_settings
                where user_id = ?
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            return UserSettings()
        return UserSettings(
            selected_symbol=str(row["selected_symbol"]),
            subscription_plan=str(row["subscription_plan"]),
            subscription_status=str(row["subscription_status"]),
        )

    def credentials_for_user(self, user_id: int) -> UserCredentials | None:
        with self._connect() as conn:
            row = conn.execute(
                "select account_address, encrypted_secret_key from credentials where user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            secret_key = self._fernet.decrypt(str(row["encrypted_secret_key"]).encode("utf-8")).decode("utf-8")
        except InvalidToken as error:
            raise ValueError("stored credentials cannot be decrypted") from error
        return UserCredentials(account_address=str(row["account_address"]), secret_key=secret_key)

    def has_credentials(self, user_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute("select 1 from credentials where user_id = ?", (user_id,)).fetchone()
        return row is not None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists users(
                  id integer primary key,
                  username text not null unique,
                  password_salt text not null,
                  password_hash text not null,
                  created_at real not null
                );
                create table if not exists sessions(
                  token text primary key,
                  user_id integer not null references users(id) on delete cascade,
                  expires_at real not null
                );
                create table if not exists credentials(
                  user_id integer primary key references users(id) on delete cascade,
                  account_address text not null,
                  encrypted_secret_key text not null,
                  updated_at real not null
                );
                create table if not exists user_settings(
                  user_id integer primary key references users(id) on delete cascade,
                  selected_symbol text not null,
                  subscription_plan text not null,
                  subscription_status text not null,
                  updated_at real not null
                );
                """
            )

    @staticmethod
    def _validate_username_password(username: str, password: str) -> None:
        if len(username) < 3:
            raise ValueError("username must be at least 3 characters")
        if len(password) < 8:
            raise ValueError("password must be at least 8 characters")

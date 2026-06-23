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
REMEMBERED_SESSION_SECONDS = 60 * 60 * 24 * 90
PASSWORD_RESET_CODE_SECONDS = 60 * 10
LOGIN_CODE_SECONDS = 60 * 10
COINGLASS_STARTUP_INTERVALS = {"30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "1w"}


@dataclass(frozen=True)
class User:
    id: int
    username: str


@dataclass(frozen=True)
class UserCredentials:
    account_address: str
    secret_key: str


@dataclass(frozen=True)
class LoginHint:
    username: str
    last_login_at: float
    last_seen_at: float


@dataclass(frozen=True)
class PasswordResetCode:
    user: User
    code: str
    expires_at: float


@dataclass(frozen=True)
class LoginCode:
    user: User
    code: str
    expires_at: float


@dataclass(frozen=True)
class UserSettings:
    selected_symbol: str = "BTC"
    subscription_plan: str = "free"
    subscription_status: str = "active"
    chart_interval: str = "1h"
    signal_session_window: str = "london_new_york"
    leverage: float = 10.0
    order_quote_size: float = 25.0
    max_order_notional: float = 25.0
    max_total_notional: float = 5000.0
    max_position_value: float = 5000.0
    session_guard_minutes: int = 60
    stale_grid_cancel: bool = True
    london_commodity_only: bool = True
    max_daily_loss_pct: float = 0.05


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

    def record_login(self, user_id: int, username: str, ip_address: str) -> None:
        ip_hash = self._hash_ip(ip_address)
        if not ip_hash:
            return
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                insert into login_hints(ip_hash, user_id, username, last_login_at, last_seen_at)
                values (?, ?, ?, ?, ?)
                on conflict(ip_hash) do update set
                  user_id = excluded.user_id,
                  username = excluded.username,
                  last_login_at = excluded.last_login_at,
                  last_seen_at = excluded.last_seen_at
                """,
                (ip_hash, user_id, username.strip().lower(), now, now),
            )

    def touch_seen(self, user_id: int, username: str, ip_address: str) -> None:
        ip_hash = self._hash_ip(ip_address)
        if not ip_hash:
            return
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                insert into login_hints(ip_hash, user_id, username, last_login_at, last_seen_at)
                values (?, ?, ?, ?, ?)
                on conflict(ip_hash) do update set
                  user_id = excluded.user_id,
                  username = excluded.username,
                  last_seen_at = excluded.last_seen_at
                """,
                (ip_hash, user_id, username.strip().lower(), now, now),
            )

    def login_hint_for_ip(self, ip_address: str) -> LoginHint | None:
        ip_hash = self._hash_ip(ip_address)
        if not ip_hash:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "select username, last_login_at, last_seen_at from login_hints where ip_hash = ?",
                (ip_hash,),
            ).fetchone()
        if row is None:
            return None
        return LoginHint(
            username=str(row["username"]),
            last_login_at=float(row["last_login_at"] or 0),
            last_seen_at=float(row["last_seen_at"] or 0),
        )

    def create_password_reset_code(self, username: str) -> PasswordResetCode | None:
        username = username.strip().lower()
        with self._connect() as conn:
            row = conn.execute("select id, username from users where username = ?", (username,)).fetchone()
            if row is None:
                return None
            code = f"{secrets.randbelow(1_000_000):06d}"
            salt, digest = _hash_password(code)
            expires_at = time.time() + PASSWORD_RESET_CODE_SECONDS
            conn.execute("delete from password_resets where user_id = ?", (int(row["id"]),))
            conn.execute(
                """
                insert into password_resets(user_id, code_salt, code_hash, expires_at, created_at)
                values (?, ?, ?, ?, ?)
                """,
                (int(row["id"]), salt, digest, expires_at, time.time()),
            )
        return PasswordResetCode(
            user=User(id=int(row["id"]), username=str(row["username"])),
            code=code,
            expires_at=expires_at,
        )

    def create_login_code(self, username: str) -> LoginCode | None:
        username = username.strip().lower()
        with self._connect() as conn:
            row = conn.execute("select id, username from users where username = ?", (username,)).fetchone()
            if row is None:
                return None
            code = f"{secrets.randbelow(1_000_000):06d}"
            salt, digest = _hash_password(code)
            expires_at = time.time() + LOGIN_CODE_SECONDS
            conn.execute("delete from login_codes where user_id = ?", (int(row["id"]),))
            conn.execute(
                """
                insert into login_codes(user_id, code_salt, code_hash, expires_at, created_at)
                values (?, ?, ?, ?, ?)
                """,
                (int(row["id"]), salt, digest, expires_at, time.time()),
            )
        return LoginCode(
            user=User(id=int(row["id"]), username=str(row["username"])),
            code=code,
            expires_at=expires_at,
        )

    def authenticate_login_code(self, username: str, code: str) -> User | None:
        username = username.strip().lower()
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                """
                select users.id, users.username, login_codes.code_salt, login_codes.code_hash,
                       login_codes.expires_at
                from users
                join login_codes on login_codes.user_id = users.id
                where users.username = ?
                """,
                (username,),
            ).fetchone()
            conn.execute("delete from login_codes where expires_at < ?", (now,))
            if row is None or float(row["expires_at"]) < now:
                return None
            _, expected = _hash_password(code.strip(), row["code_salt"])
            if not hmac.compare_digest(expected, row["code_hash"]):
                return None
            user_id = int(row["id"])
            conn.execute("delete from login_codes where user_id = ?", (user_id,))
        return User(id=user_id, username=str(row["username"]))

    def reset_password_with_code(self, username: str, code: str, new_password: str) -> User | None:
        username = username.strip().lower()
        self._validate_username_password(username, new_password)
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                """
                select users.id, users.username, password_resets.code_salt, password_resets.code_hash,
                       password_resets.expires_at
                from users
                join password_resets on password_resets.user_id = users.id
                where users.username = ?
                """,
                (username,),
            ).fetchone()
            conn.execute("delete from password_resets where expires_at < ?", (now,))
            if row is None or float(row["expires_at"]) < now:
                return None
            _, expected = _hash_password(code.strip(), row["code_salt"])
            if not hmac.compare_digest(expected, row["code_hash"]):
                return None
            salt, digest = _hash_password(new_password)
            user_id = int(row["id"])
            conn.execute(
                "update users set password_salt = ?, password_hash = ? where id = ?",
                (salt, digest, user_id),
            )
            conn.execute("delete from password_resets where user_id = ?", (user_id,))
            conn.execute("delete from sessions where user_id = ?", (user_id,))
        return User(id=user_id, username=str(row["username"]))

    def create_session(self, user_id: int, ttl_seconds: int = SESSION_SECONDS) -> str:
        token = secrets.token_urlsafe(32)
        ttl_seconds = max(60, int(ttl_seconds))
        with self._connect() as conn:
            conn.execute(
                "insert into sessions(token, user_id, expires_at) values (?, ?, ?)",
                (token, user_id, time.time() + ttl_seconds),
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
            raise ValueError("enter the Hyperliquid address for private sync")
        if not secret_key:
            raise ValueError("enter the API key for private sync")
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

    def save_trading_rules(
        self,
        user_id: int,
        *,
        chart_interval: str,
        london_commodity_only: bool,
        max_daily_loss_pct: float,
        session_guard_minutes: int,
        stale_grid_cancel: bool,
        order_quote_size: float | None = None,
        max_total_notional: float | None = None,
        max_position_value: float | None = None,
        signal_session_window: str | None = None,
    ) -> UserSettings:
        settings = self.settings_for_user(user_id)
        chart_interval = chart_interval.strip()
        signal_session_window = signal_session_window or "london_new_york"
        if chart_interval not in COINGLASS_STARTUP_INTERVALS:
            raise ValueError("chart interval must be 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, or 1w")
        if signal_session_window not in {"london_new_york", "always"}:
            raise ValueError("signal session window must be london_new_york or always")
        if session_guard_minutes not in {5, 15, 30, 60, 90}:
            raise ValueError("session guard must be 5, 15, 30, 60, or 90 minutes")
        if not 0 < max_daily_loss_pct <= 0.2:
            raise ValueError("drawdown limit must be greater than 0% and no more than 20%")
        order_quote_size = settings.order_quote_size if order_quote_size is None else float(order_quote_size)
        max_total_notional = settings.max_total_notional if max_total_notional is None else float(max_total_notional)
        max_position_value = settings.max_position_value if max_position_value is None else float(max_position_value)
        if order_quote_size <= 0:
            raise ValueError("per-order size must be positive")
        if max_total_notional <= 0:
            raise ValueError("total open grid limit must be positive")
        if max_position_value <= 0:
            raise ValueError("max position value must be positive")
        if order_quote_size > max_total_notional:
            raise ValueError("per-order size cannot exceed total open grid")
        with self._connect() as conn:
            conn.execute(
                """
                insert into user_settings(
                  user_id, selected_symbol, subscription_plan, subscription_status,
                  chart_interval, signal_session_window, leverage, order_quote_size, max_order_notional, max_total_notional,
                  max_position_value, session_guard_minutes, stale_grid_cancel, london_commodity_only,
                  max_daily_loss_pct, updated_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(user_id) do update set
                  chart_interval = excluded.chart_interval,
                  signal_session_window = excluded.signal_session_window,
                  leverage = excluded.leverage,
                  order_quote_size = excluded.order_quote_size,
                  max_order_notional = excluded.max_order_notional,
                  max_total_notional = excluded.max_total_notional,
                  max_position_value = excluded.max_position_value,
                  session_guard_minutes = excluded.session_guard_minutes,
                  stale_grid_cancel = excluded.stale_grid_cancel,
                  london_commodity_only = excluded.london_commodity_only,
                  max_daily_loss_pct = excluded.max_daily_loss_pct,
                  updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    settings.selected_symbol,
                    settings.subscription_plan,
                    settings.subscription_status,
                    chart_interval,
                    signal_session_window,
                    10.0,
                    order_quote_size,
                    order_quote_size,
                    max_total_notional,
                    max_position_value,
                    session_guard_minutes,
                    int(stale_grid_cancel),
                    int(london_commodity_only),
                    max_daily_loss_pct,
                    time.time(),
                ),
            )
        return self.settings_for_user(user_id)

    def save_subscription_plan(self, user_id: int, plan: str, status: str = "active") -> UserSettings:
        plan = plan.strip().lower()
        status = status.strip().lower() or "active"
        if plan not in {"free", "private"}:
            raise ValueError("unknown access plan")
        if status not in {"active", "trialing", "past_due", "canceled", "inactive"}:
            raise ValueError("unknown access status")
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
                (user_id, settings.selected_symbol, plan, status, time.time()),
            )
        return self.settings_for_user(user_id)

    def settings_for_user(self, user_id: int) -> UserSettings:
        with self._connect() as conn:
            row = conn.execute(
                """
                select selected_symbol, subscription_plan, subscription_status,
                       chart_interval, signal_session_window, leverage, order_quote_size, max_order_notional, max_total_notional,
                       max_position_value, session_guard_minutes, stale_grid_cancel, london_commodity_only,
                       max_daily_loss_pct
                from user_settings
                where user_id = ?
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            return UserSettings()
        order_quote_size = float(row["order_quote_size"] or 25.0)
        max_total_notional = float(row["max_total_notional"] or 5000.0)
        max_position_value = float(row["max_position_value"] or 5000.0)
        if max_total_notional <= 250 and max_position_value <= 250 and order_quote_size <= 25:
            max_total_notional = 5000.0
            max_position_value = 5000.0
        return UserSettings(
            selected_symbol=str(row["selected_symbol"]),
            subscription_plan=str(row["subscription_plan"]),
            subscription_status=str(row["subscription_status"]),
            chart_interval=str(row["chart_interval"] if row["chart_interval"] in COINGLASS_STARTUP_INTERVALS else "1h"),
            signal_session_window=str(row["signal_session_window"] or "london_new_york"),
            leverage=float(row["leverage"] or 10.0),
            order_quote_size=order_quote_size,
            max_order_notional=float(row["max_order_notional"] or row["order_quote_size"] or 25.0),
            max_total_notional=max_total_notional,
            max_position_value=max_position_value,
            session_guard_minutes=int(row["session_guard_minutes"] or 60),
            stale_grid_cancel=bool(row["stale_grid_cancel"]),
            london_commodity_only=bool(row["london_commodity_only"]),
            max_daily_loss_pct=float(row["max_daily_loss_pct"] or 0.05),
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
                create table if not exists password_resets(
                  user_id integer primary key references users(id) on delete cascade,
                  code_salt text not null,
                  code_hash text not null,
                  expires_at real not null,
                  created_at real not null
                );
                create table if not exists login_codes(
                  user_id integer primary key references users(id) on delete cascade,
                  code_salt text not null,
                  code_hash text not null,
                  expires_at real not null,
                  created_at real not null
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
                  chart_interval text not null default '1h',
                  signal_session_window text not null default 'london_new_york',
                  leverage real not null default 10,
                  order_quote_size real not null default 25,
                  max_order_notional real not null default 25,
                  max_total_notional real not null default 5000,
                  max_position_value real not null default 5000,
                  session_guard_minutes integer not null default 60,
                  stale_grid_cancel integer not null default 1,
                  london_commodity_only integer not null default 1,
                  max_daily_loss_pct real not null default 0.05,
                  updated_at real not null
                );
                create table if not exists login_hints(
                  ip_hash text primary key,
                  user_id integer not null references users(id) on delete cascade,
                  username text not null,
                  last_login_at real not null,
                  last_seen_at real not null
                );
                """
            )
            existing = {
                str(row["name"])
                for row in conn.execute("pragma table_info(user_settings)").fetchall()
            }
            migrations = {
                "chart_interval": "alter table user_settings add column chart_interval text not null default '1h'",
                "signal_session_window": "alter table user_settings add column signal_session_window text not null default 'london_new_york'",
                "leverage": "alter table user_settings add column leverage real not null default 10",
                "order_quote_size": "alter table user_settings add column order_quote_size real not null default 25",
                "max_order_notional": "alter table user_settings add column max_order_notional real not null default 25",
                "max_total_notional": "alter table user_settings add column max_total_notional real not null default 5000",
                "max_position_value": "alter table user_settings add column max_position_value real not null default 5000",
                "session_guard_minutes": "alter table user_settings add column session_guard_minutes integer not null default 60",
                "stale_grid_cancel": "alter table user_settings add column stale_grid_cancel integer not null default 1",
                "london_commodity_only": "alter table user_settings add column london_commodity_only integer not null default 1",
                "max_daily_loss_pct": "alter table user_settings add column max_daily_loss_pct real not null default 0.05",
            }
            for column, statement in migrations.items():
                if column not in existing:
                    conn.execute(statement)

    @staticmethod
    def _validate_username_password(username: str, password: str) -> None:
        if len(username) < 3:
            raise ValueError("username must be at least 3 characters")
        if len(password) < 8:
            raise ValueError("password must be at least 8 characters")

    @staticmethod
    def _hash_ip(ip_address: str) -> str:
        normalized = ip_address.strip()
        if not normalized:
            return ""
        pepper = secret_value("MONATISE_LOGIN_HINT_PEPPER", "") or secret_value("MONATISE_ENCRYPTION_KEY", "")
        pepper = pepper or "monatise-login-hint-development-pepper"
        return hashlib.sha256(f"{pepper}:{normalized}".encode("utf-8")).hexdigest()

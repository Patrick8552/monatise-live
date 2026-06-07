from __future__ import annotations

import os
from dataclasses import dataclass

from monatise.live.secrets import secret_value


LIVE_CONFIRMATION = "I_UNDERSTAND_REAL_MONEY"


@dataclass(frozen=True)
class RuntimeConfig:
    mode: str = "paper"
    network: str = "testnet"
    symbol: str = "BTC"
    quote: float = 10_000.0
    base: float = 0.05
    spacing_pct: float = 0.005
    levels_each_side: int = 5
    order_quote_size: float = 250.0
    fee_rate: float = 0.0004
    poll_seconds: float = 5.0
    execution_mode: str = "dry_run"
    max_order_notional: float = 250.0
    max_total_notional: float | None = None
    max_base_inventory: float = 0.1
    max_daily_loss: float = 100.0
    max_mark_move_pct: float = 0.03
    max_position_value: float = 1_000.0
    min_account_value: float = 0.0
    order_refresh_seconds: float = 30.0
    session_guard_minutes: int = 60
    chart_interval: str = "1h"
    london_commodity_only: bool = True
    stale_grid_cancel: bool = True
    allow_live_orders: bool = False
    live_confirmation: str = ""
    account_address: str = ""
    secret_key: str = ""
    assets: tuple[str, ...] = ("BTC", "ETH", "SOL", "HYPE", "BNB", "XRP", "DOGE", "GOLD", "CL", "BRENTOIL")
    builder_dexes: tuple[str, ...] = ("xyz",)

    def __post_init__(self) -> None:
        if self.max_total_notional is None:
            object.__setattr__(self, "max_total_notional", self.quote)

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        quote = float(os.getenv("MONATISE_QUOTE", "10000"))
        max_total_notional = os.getenv("MONATISE_MAX_TOTAL_NOTIONAL")
        return cls(
            mode=os.getenv("MONATISE_MODE", "paper").lower(),
            network=os.getenv("MONATISE_NETWORK", "testnet").lower(),
            symbol=os.getenv("MONATISE_SYMBOL", "BTC"),
            quote=quote,
            base=float(os.getenv("MONATISE_BASE", "0.05")),
            spacing_pct=float(os.getenv("MONATISE_SPACING_PCT", "0.005")),
            levels_each_side=int(os.getenv("MONATISE_LEVELS_EACH_SIDE", "5")),
            order_quote_size=float(os.getenv("MONATISE_ORDER_QUOTE_SIZE", "250")),
            fee_rate=float(os.getenv("MONATISE_FEE_RATE", "0.0004")),
            poll_seconds=float(os.getenv("MONATISE_POLL_SECONDS", "5")),
            execution_mode=os.getenv("MONATISE_EXECUTION_MODE", "dry_run").lower(),
            max_order_notional=float(os.getenv("MONATISE_MAX_ORDER_NOTIONAL", "250")),
            max_total_notional=float(max_total_notional) if max_total_notional else quote,
            max_base_inventory=float(os.getenv("MONATISE_MAX_BASE_INVENTORY", "0.1")),
            max_daily_loss=float(os.getenv("MONATISE_MAX_DAILY_LOSS", "100")),
            max_mark_move_pct=float(os.getenv("MONATISE_MAX_MARK_MOVE_PCT", "0.03")),
            max_position_value=float(os.getenv("MONATISE_MAX_POSITION_VALUE", "1000")),
            min_account_value=float(os.getenv("MONATISE_MIN_ACCOUNT_VALUE", "0")),
            order_refresh_seconds=float(os.getenv("MONATISE_ORDER_REFRESH_SECONDS", "30")),
            session_guard_minutes=int(os.getenv("MONATISE_SESSION_GUARD_MINUTES", "60")),
            chart_interval=os.getenv("MONATISE_CHART_INTERVAL", "1h"),
            london_commodity_only=os.getenv("MONATISE_LONDON_COMMODITY_ONLY", "true").lower() == "true",
            stale_grid_cancel=os.getenv("MONATISE_STALE_GRID_CANCEL", "true").lower() == "true",
            allow_live_orders=os.getenv("MONATISE_ALLOW_LIVE_ORDERS", "false").lower() == "true",
            live_confirmation=secret_value("MONATISE_LIVE_CONFIRMATION", ""),
            account_address=(
                secret_value("HYPERLIQUID_ACCOUNT_ADDRESS", "")
                if os.getenv("MONATISE_ENABLE_GLOBAL_CREDENTIALS", "false").lower() == "true"
                else ""
            ),
            secret_key=(
                secret_value("HYPERLIQUID_SECRET_KEY", "")
                if os.getenv("MONATISE_ENABLE_GLOBAL_CREDENTIALS", "false").lower() == "true"
                else ""
            ),
            assets=tuple(
                asset.strip().upper()
                for asset in os.getenv("MONATISE_ASSETS", "BTC,ETH,SOL,HYPE,BNB,XRP,DOGE,GOLD,CL,BRENTOIL").split(",")
                if asset.strip()
            ),
            builder_dexes=tuple(
                dex.strip()
                for dex in os.getenv("MONATISE_BUILDER_DEXES", "xyz").split(",")
                if dex.strip()
            ),
        )

    @property
    def live_enabled(self) -> bool:
        return (
            self.mode == "live"
            and self.execution_mode == "live"
            and self.allow_live_orders
            and self.live_confirmation == LIVE_CONFIRMATION
            and bool(self.secret_key)
            and bool(self.account_address)
        )

    def validate(self) -> None:
        if self.mode not in {"paper", "live"}:
            raise ValueError("MONATISE_MODE must be paper or live")
        if self.network not in {"testnet", "mainnet"}:
            raise ValueError("MONATISE_NETWORK must be testnet or mainnet")
        if self.execution_mode not in {"observe", "dry_run", "live"}:
            raise ValueError("MONATISE_EXECUTION_MODE must be observe, dry_run, or live")
        if self.order_quote_size <= 0:
            raise ValueError("MONATISE_ORDER_QUOTE_SIZE must be positive")
        if self.max_order_notional <= 0:
            raise ValueError("MONATISE_MAX_ORDER_NOTIONAL must be positive")
        if self.order_quote_size > self.max_order_notional:
            raise ValueError("order quote size cannot exceed max order notional")
        if self.max_total_notional <= 0:
            raise ValueError("MONATISE_MAX_TOTAL_NOTIONAL must be positive")
        if self.max_mark_move_pct <= 0:
            raise ValueError("MONATISE_MAX_MARK_MOVE_PCT must be positive")
        if self.order_refresh_seconds <= 0:
            raise ValueError("MONATISE_ORDER_REFRESH_SECONDS must be positive")
        if self.session_guard_minutes not in {5, 15, 30, 60, 90}:
            raise ValueError("MONATISE_SESSION_GUARD_MINUTES must be 5, 15, 30, 60, or 90")
        if self.chart_interval not in {"1h", "15m", "5m", "1m"}:
            raise ValueError("MONATISE_CHART_INTERVAL must be 1h, 15m, 5m, or 1m")

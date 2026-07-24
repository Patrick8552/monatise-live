from __future__ import annotations

import os
from dataclasses import dataclass

from monatise.live.secrets import secret_value


LIVE_CONFIRMATION = "EXECUTION_DISABLED"
COINGLASS_STARTUP_INTERVALS = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "1w"}
COINGLASS_STARTUP_INTERVAL_LABEL = "1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, or 1w"


@dataclass(frozen=True)
class RuntimeConfig:
    mode: str = "paper"
    network: str = "testnet"
    symbol: str = "BTC"
    quote: float = 10_000.0
    base: float = 0.05
    spacing_pct: float = 0.005
    levels_each_side: int = 5
    leverage: float = 10.0
    order_quote_size: float = 250.0
    fee_rate: float = 0.0004
    poll_seconds: float = 5.0
    execution_mode: str = "disabled"
    max_order_notional: float = 250.0
    max_total_notional: float | None = None
    max_base_inventory: float = 0.1
    max_daily_loss: float = 500.0
    max_daily_loss_pct: float | None = None
    max_mark_move_pct: float = 0.03
    max_position_value: float = 1_000.0
    min_account_value: float = 0.0
    order_refresh_seconds: float = 30.0
    session_guard_minutes: int = 60
    chart_interval: str = "1h"
    signal_session_window: str = "always"
    london_commodity_only: bool = False
    stale_grid_cancel: bool = True
    allow_live_orders: bool = False
    live_confirmation: str = ""
    account_address: str = ""
    secret_key: str = ""
    data_feed: str = "coinglass"
    exchange: str = "hyperliquid"
    assets: tuple[str, ...] = ("BTC", "ETH", "SOL", "HYPE", "BNB", "XRP", "DOGE")
    builder_dexes: tuple[str, ...] = ("xyz",)
    tradingview_webhook_token: str = ""

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
            leverage=float(os.getenv("MONATISE_LEVERAGE", "10")),
            order_quote_size=float(os.getenv("MONATISE_ORDER_QUOTE_SIZE", "250")),
            fee_rate=float(os.getenv("MONATISE_FEE_RATE", "0.0004")),
            poll_seconds=float(os.getenv("MONATISE_POLL_SECONDS", "5")),
            execution_mode="disabled",
            max_order_notional=float(os.getenv("MONATISE_MAX_ORDER_NOTIONAL", "250")),
            max_total_notional=float(max_total_notional) if max_total_notional else quote,
            max_base_inventory=float(os.getenv("MONATISE_MAX_BASE_INVENTORY", "0.1")),
            max_daily_loss=float(os.getenv("MONATISE_MAX_DAILY_LOSS", str(quote * 0.05))),
            max_daily_loss_pct=float(os.getenv("MONATISE_MAX_DAILY_LOSS_PCT", "0.05")),
            max_mark_move_pct=float(os.getenv("MONATISE_MAX_MARK_MOVE_PCT", "0.03")),
            max_position_value=float(os.getenv("MONATISE_MAX_POSITION_VALUE", "1000")),
            min_account_value=float(os.getenv("MONATISE_MIN_ACCOUNT_VALUE", "0")),
            order_refresh_seconds=float(os.getenv("MONATISE_ORDER_REFRESH_SECONDS", "30")),
            session_guard_minutes=int(os.getenv("MONATISE_SESSION_GUARD_MINUTES", "60")),
            chart_interval=os.getenv("MONATISE_CHART_INTERVAL", "1h"),
            signal_session_window=os.getenv("MONATISE_SIGNAL_SESSION_WINDOW", "always"),
            london_commodity_only=False,
            stale_grid_cancel=os.getenv("MONATISE_STALE_GRID_CANCEL", "true").lower() == "true",
            allow_live_orders=False,
            live_confirmation="",
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
            data_feed=os.getenv("MONATISE_DATA_FEED", "coinglass").lower(),
            exchange=os.getenv("MONATISE_EXCHANGE", "hyperliquid").lower(),
            assets=tuple(
                asset.strip().upper()
                for asset in os.getenv("MONATISE_ASSETS", "BTC,ETH,SOL,HYPE,BNB,XRP,DOGE").split(",")
                if asset.strip()
            ),
            builder_dexes=tuple(
                dex.strip()
                for dex in os.getenv("MONATISE_BUILDER_DEXES", "xyz").split(",")
                if dex.strip()
            ),
            tradingview_webhook_token=secret_value("MONATISE_TRADINGVIEW_WEBHOOK_TOKEN", ""),
        )

    @property
    def live_enabled(self) -> bool:
        """Order execution is globally disabled; Monatise Live is analysis-only."""
        return False

    def validate(self) -> None:
        if self.mode not in {"paper", "live"}:
            raise ValueError("MONATISE_MODE must be paper or live")
        if self.network not in {"testnet", "mainnet"}:
            raise ValueError("MONATISE_NETWORK must be testnet or mainnet")
        if self.execution_mode not in {"disabled", "observe", "dry_run", "live"}:
            raise ValueError("MONATISE_EXECUTION_MODE must be disabled, observe, dry_run, or live")
        if self.data_feed not in {"coinglass", "hyperliquid"}:
            raise ValueError("MONATISE_DATA_FEED must be coinglass or hyperliquid")
        if self.exchange not in {"hyperliquid", "backpack"}:
            raise ValueError("MONATISE_EXCHANGE must be hyperliquid or backpack")
        if self.leverage <= 0:
            raise ValueError("MONATISE_LEVERAGE must be positive")
        if self.order_quote_size <= 0:
            raise ValueError("MONATISE_ORDER_QUOTE_SIZE must be positive")
        if self.max_order_notional <= 0:
            raise ValueError("MONATISE_MAX_ORDER_NOTIONAL must be positive")
        if self.order_quote_size > self.max_order_notional:
            raise ValueError("order quote size cannot exceed max order notional")
        if self.max_total_notional <= 0:
            raise ValueError("MONATISE_MAX_TOTAL_NOTIONAL must be positive")
        if self.max_daily_loss <= 0:
            raise ValueError("MONATISE_MAX_DAILY_LOSS must be positive")
        if self.max_daily_loss_pct is not None and not 0 < self.max_daily_loss_pct <= 0.2:
            raise ValueError("MONATISE_MAX_DAILY_LOSS_PCT must be greater than 0 and no more than 0.2")
        if self.max_mark_move_pct <= 0:
            raise ValueError("MONATISE_MAX_MARK_MOVE_PCT must be positive")
        if self.order_refresh_seconds <= 0:
            raise ValueError("MONATISE_ORDER_REFRESH_SECONDS must be positive")
        if self.session_guard_minutes not in {5, 15, 30, 60, 90}:
            raise ValueError("MONATISE_SESSION_GUARD_MINUTES must be 5, 15, 30, 60, or 90")
        if self.chart_interval not in COINGLASS_STARTUP_INTERVALS:
            raise ValueError(f"MONATISE_CHART_INTERVAL must be one of {COINGLASS_STARTUP_INTERVAL_LABEL}")
        if self.signal_session_window != "always":
            raise ValueError("MONATISE_SIGNAL_SESSION_WINDOW is fixed to always")

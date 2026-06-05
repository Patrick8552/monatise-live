from __future__ import annotations

import os
from dataclasses import dataclass


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
    max_order_notional: float = 250.0
    max_total_notional: float = 1_500.0
    max_base_inventory: float = 0.1
    max_daily_loss: float = 100.0
    allow_live_orders: bool = False
    live_confirmation: str = ""
    account_address: str = ""
    secret_key: str = ""

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        return cls(
            mode=os.getenv("MONATISE_MODE", "paper").lower(),
            network=os.getenv("MONATISE_NETWORK", "testnet").lower(),
            symbol=os.getenv("MONATISE_SYMBOL", "BTC"),
            quote=float(os.getenv("MONATISE_QUOTE", "10000")),
            base=float(os.getenv("MONATISE_BASE", "0.05")),
            spacing_pct=float(os.getenv("MONATISE_SPACING_PCT", "0.005")),
            levels_each_side=int(os.getenv("MONATISE_LEVELS_EACH_SIDE", "5")),
            order_quote_size=float(os.getenv("MONATISE_ORDER_QUOTE_SIZE", "250")),
            fee_rate=float(os.getenv("MONATISE_FEE_RATE", "0.0004")),
            poll_seconds=float(os.getenv("MONATISE_POLL_SECONDS", "5")),
            max_order_notional=float(os.getenv("MONATISE_MAX_ORDER_NOTIONAL", "250")),
            max_total_notional=float(os.getenv("MONATISE_MAX_TOTAL_NOTIONAL", "1500")),
            max_base_inventory=float(os.getenv("MONATISE_MAX_BASE_INVENTORY", "0.1")),
            max_daily_loss=float(os.getenv("MONATISE_MAX_DAILY_LOSS", "100")),
            allow_live_orders=os.getenv("MONATISE_ALLOW_LIVE_ORDERS", "false").lower() == "true",
            live_confirmation=os.getenv("MONATISE_LIVE_CONFIRMATION", ""),
            account_address=os.getenv("HYPERLIQUID_ACCOUNT_ADDRESS", ""),
            secret_key=os.getenv("HYPERLIQUID_SECRET_KEY", ""),
        )

    @property
    def live_enabled(self) -> bool:
        return (
            self.mode == "live"
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
        if self.order_quote_size <= 0:
            raise ValueError("MONATISE_ORDER_QUOTE_SIZE must be positive")
        if self.max_order_notional <= 0:
            raise ValueError("MONATISE_MAX_ORDER_NOTIONAL must be positive")
        if self.order_quote_size > self.max_order_notional:
            raise ValueError("order quote size cannot exceed max order notional")

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from monatise.core.models import Order, OrderSide
from monatise.core.ports import ExecutionPort, MarketDataPort
from monatise.live.config import RuntimeConfig


@dataclass(frozen=True)
class SubmittedOrder:
    local_order_id: str
    exchange_response: dict[str, Any]


class HyperliquidAdapter(MarketDataPort, ExecutionPort):
    """Hyperliquid adapter using the official `hyperliquid-python-sdk`.

    Install for live use:
        pip install hyperliquid-python-sdk
    """

    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        try:
            import eth_account
            from hyperliquid.exchange import Exchange
            from hyperliquid.info import Info
            from hyperliquid.utils import constants
        except ImportError as error:
            raise RuntimeError(
                "Live Hyperliquid mode requires `pip install hyperliquid-python-sdk`."
            ) from error

        base_url = constants.MAINNET_API_URL if config.network == "mainnet" else constants.TESTNET_API_URL
        self.account_address = config.account_address
        self.info = Info(base_url, skip_ws=True)
        self.account = eth_account.Account.from_key(config.secret_key) if config.secret_key else None
        self.exchange = (
            Exchange(self.account, base_url, account_address=self.account_address)
            if self.account and self.account_address
            else None
        )

    def latest_price(self, symbol: str) -> float:
        coin = self._coin(symbol)
        mids = self.info.all_mids()
        if coin not in mids:
            raise RuntimeError(f"{coin} was not found in Hyperliquid all_mids response")
        return float(mids[coin])

    def candles(self, symbol: str, limit: int):  # noqa: ANN201
        raise NotImplementedError("live candle history is not wired yet; use latest_price polling")

    def place_orders(self, orders: list[Order]) -> list[SubmittedOrder]:
        if not self.config.live_enabled:
            raise RuntimeError("live orders are disabled by environment safety gates")
        if self.exchange is None:
            raise RuntimeError("Hyperliquid exchange client is not initialized")

        submitted: list[SubmittedOrder] = []
        for order in orders:
            price = self._order_price(order.price)
            quantity = self._order_quantity(order.quantity)
            response = self.exchange.order(
                self._coin(order.symbol),
                order.side is OrderSide.BUY,
                quantity,
                price,
                {"limit": {"tif": "Gtc"}},
                reduce_only=False,
            )
            submitted.append(SubmittedOrder(order.order_id, response))
        return submitted

    def cancel_orders(self, order_ids: list[str]) -> None:
        raise NotImplementedError("cancel requires exchange order ids from placement responses")

    def fills(self, symbol: str):  # noqa: ANN201
        raise NotImplementedError("fill reconciliation is planned through user fills/order status polling")

    def user_state(self) -> dict[str, Any]:
        if not self.account_address:
            raise RuntimeError("HYPERLIQUID_ACCOUNT_ADDRESS is required for user_state")
        return self.info.user_state(self.account_address)

    def spot_user_state(self) -> dict[str, Any]:
        if not self.account_address:
            raise RuntimeError("HYPERLIQUID_ACCOUNT_ADDRESS is required for spot_user_state")
        return self.info.spot_user_state(self.account_address)

    def vault_equities(self) -> list[dict[str, Any]]:
        if not self.account_address:
            return []
        return self.info.user_vault_equities(self.account_address)

    def _coin(self, symbol: str) -> str:
        return symbol.split("-", 1)[0].upper()

    def _order_price(self, price: float) -> float:
        return round(price, 1)

    def _order_quantity(self, quantity: float) -> float:
        return round(quantity, 5)

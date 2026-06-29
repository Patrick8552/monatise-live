from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from monatise.core.models import Candle, Order, OrderSide
from monatise.core.ports import ExecutionPort, MarketDataPort
from monatise.live.config import RuntimeConfig


BUILDER_ASSET_ALIASES = {}


@dataclass(frozen=True)
class SubmittedOrder:
    local_order_id: str
    exchange_order_id: str
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
        mids = self._all_mids()
        if coin not in mids:
            raise RuntimeError(f"{coin} was not found in Hyperliquid all_mids response")
        return float(mids[coin])

    def latest_prices(self, symbols: list[str] | tuple[str, ...]) -> dict[str, float]:
        mids = self._all_mids()
        prices: dict[str, float] = {}
        for symbol in symbols:
            coin = self._coin(symbol)
            if coin in mids:
                prices[symbol.upper()] = float(mids[coin])
        return prices

    def all_prices(self) -> dict[str, float]:
        mids = self._all_mids()
        prices = {str(coin): float(price) for coin, price in mids.items()}
        for alias, coin in BUILDER_ASSET_ALIASES.items():
            if coin in prices:
                prices[alias] = prices[coin]
        return prices

    def candles(self, symbol: str, limit: int, interval: str = "1h") -> list[Candle]:
        if limit <= 0:
            raise ValueError("candle limit must be positive")
        end_time = int(time.time() * 1000)
        start_time = end_time - (_interval_millis(interval) * max(1, limit + 2))
        raw_candles = self.info.post(
            "/info",
            {
                "type": "candleSnapshot",
                "req": {
                    "coin": self._coin(symbol),
                    "interval": interval,
                    "startTime": start_time,
                    "endTime": end_time,
                },
            },
        )
        candles = [_parse_candle(raw) for raw in raw_candles][-limit:]
        for candle in candles:
            candle.validate()
        return candles

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
            submitted.append(
                SubmittedOrder(
                    local_order_id=order.order_id,
                    exchange_order_id=self._exchange_order_id(response),
                    exchange_response=response,
                )
            )
        return submitted

    def cancel_orders(self, order_ids: list[str]) -> None:
        if not order_ids:
            return
        if self.exchange is None:
            raise RuntimeError("Hyperliquid exchange client is not initialized")
        coin = self._coin(self.config.symbol)
        for order_id in order_ids:
            self.exchange.cancel(coin, int(order_id))

    def fills(self, symbol: str) -> list[dict[str, Any]]:
        if not self.account_address:
            raise RuntimeError("HYPERLIQUID_ACCOUNT_ADDRESS is required for fills")
        coin = self._coin(symbol)
        return [fill for fill in self.info.user_fills(self.account_address) if fill.get("coin") == coin]

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
        coin = symbol.split("-", 1)[0]
        if ":" in coin:
            dex, _, market = coin.partition(":")
            return f"{dex.lower()}:{market.upper()}"
        return BUILDER_ASSET_ALIASES.get(coin.upper(), coin.upper())

    def _all_mids(self) -> dict[str, str]:
        mids = dict(self.info.all_mids())
        for dex in self.config.builder_dexes:
            try:
                mids.update(self.info.post("/info", {"type": "allMids", "dex": dex}))
            except Exception:  # noqa: BLE001
                continue
        return mids

    def _order_price(self, price: float) -> float:
        return round(price, 1)

    def _order_quantity(self, quantity: float) -> float:
        return round(quantity, 5)

    def _exchange_order_id(self, response: dict[str, Any]) -> str:
        statuses = response.get("response", {}).get("data", {}).get("statuses", [])
        for status in statuses:
            resting = status.get("resting")
            if resting and "oid" in resting:
                return str(resting["oid"])
            filled = status.get("filled")
            if filled and "oid" in filled:
                return str(filled["oid"])
        return ""


def _interval_millis(interval: str) -> int:
    units = {
        "1m": 60_000,
        "5m": 5 * 60_000,
        "15m": 15 * 60_000,
        "1h": 60 * 60_000,
        "4h": 4 * 60 * 60_000,
        "1d": 24 * 60 * 60_000,
    }
    try:
        return units[interval]
    except KeyError as error:
        raise ValueError("unsupported Hyperliquid candle interval") from error


def _parse_candle(raw: dict[str, Any]) -> Candle:
    timestamp = raw.get("t", raw.get("T", raw.get("time", "")))
    return Candle(
        timestamp=str(timestamp),
        open=float(raw["o"]),
        high=float(raw["h"]),
        low=float(raw["l"]),
        close=float(raw["c"]),
        volume=float(raw.get("v", 0.0)),
    )

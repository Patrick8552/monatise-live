from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from monatise.adapters.hyperliquid import HyperliquidAdapter
from monatise.core.models import Candle, Fill, Order, OrderSide, Portfolio
from monatise.live.config import RuntimeConfig
from monatise.live.risk import RiskDecision, RiskManager
from monatise.sim.csv_data import load_candles
from monatise.strategy.harvester import LiquidityHarvester, LiquidityHarvesterConfig


@dataclass
class RuntimeEvent:
    timestamp: float
    level: str
    message: str


@dataclass
class RuntimeState:
    running: bool = False
    mode: str = "paper"
    network: str = "testnet"
    symbol: str = "BTC"
    mark_price: float = 0.0
    portfolio: Portfolio = field(default_factory=lambda: Portfolio(quote=0))
    open_orders: list[Order] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)
    events: list[RuntimeEvent] = field(default_factory=list)
    live_ready: bool = False
    risk_status: str = "ready"
    account: dict = field(default_factory=dict)
    last_order_refresh: float = 0.0
    last_mark_price: float = 0.0
    exchange_order_ids: dict[str, str] = field(default_factory=dict)
    reconciled_fill_ids: set[str] = field(default_factory=set)
    last_reconciliation: float = 0.0


class TradingService:
    def __init__(self, config: RuntimeConfig) -> None:
        config.validate()
        self.config = config
        self.portfolio = Portfolio(quote=config.quote, base=config.base)
        self._paper_candles = self._load_paper_candles()
        initial_mark = self._paper_candles[0].open if self._paper_candles else 1
        self.harvester = self._build_harvester(initial_mark)
        self.risk = RiskManager(config, self.portfolio.equity(initial_mark))
        self.state = RuntimeState(
            mode=config.mode,
            network=config.network,
            symbol=config.symbol,
            portfolio=self.portfolio,
            live_ready=config.live_enabled,
        )
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._paper_index = 0
        self._adapter = None
        self._live_baseline_initialized = False

    def start(self) -> dict:
        with self._lock:
            if self.state.running:
                return self._snapshot_unlocked()
            self._stop.clear()
            if self.config.mode == "live":
                self._live_baseline_initialized = False
            self.risk.resume()
            self.state.running = True
            self._event("info", f"starting {self.config.mode} trading loop")
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()
            return self._snapshot_unlocked()

    def stop(self) -> dict:
        self._stop.set()
        self.risk.stop()
        if self.config.mode == "live":
            self._cancel_live_orders("kill switch cancel")
        with self._lock:
            self.state.running = False
            self.state.risk_status = "stopped"
            self.state.open_orders = []
            self.state.exchange_order_ids = {}
            self._event("warn", "kill switch activated")
            return self._snapshot_unlocked()

    def snapshot(self) -> dict:
        if self.config.mode == "live" and not self.state.running:
            self._refresh_live_status()
        with self._lock:
            return self._snapshot_unlocked()

    def requirements(self) -> list[str]:
        missing = []
        if self.config.mode == "live":
            if self.config.execution_mode != "live":
                missing.append("MONATISE_EXECUTION_MODE=live")
            if not self.config.secret_key:
                missing.append("HYPERLIQUID_SECRET_KEY")
            if not self.config.account_address:
                missing.append("HYPERLIQUID_ACCOUNT_ADDRESS")
            if not self.config.allow_live_orders:
                missing.append("MONATISE_ALLOW_LIVE_ORDERS=true")
            if not self.config.live_confirmation:
                missing.append("MONATISE_LIVE_CONFIRMATION=I_UNDERSTAND_REAL_MONEY")
        return missing

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                if self.config.mode == "live":
                    self._live_tick()
                else:
                    self._paper_tick()
            except Exception as error:  # noqa: BLE001
                with self._lock:
                    self.state.running = False
                    self.state.risk_status = "error"
                    self._event("error", str(error))
                break
            time.sleep(self.config.poll_seconds)

    def _snapshot_unlocked(self) -> dict:
        mark = self.state.mark_price or self._paper_candles[0].open
        return {
            "running": self.state.running,
            "mode": self.state.mode,
            "network": self.state.network,
            "executionMode": self.config.execution_mode,
            "symbol": self.state.symbol,
            "markPrice": self.state.mark_price,
            "portfolio": {
                "quote": self.portfolio.quote,
                "base": self.portfolio.base,
                "equity": self.portfolio.equity(mark),
                "inventoryRatio": self.portfolio.inventory_ratio(mark),
                "realizedHarvest": self.portfolio.realized_harvest,
                "feePaid": self.portfolio.fee_paid,
            },
            "openOrders": [asdict(order) for order in self.state.open_orders],
            "fills": [asdict(fill) for fill in self.state.fills[-50:]],
            "events": [asdict(event) for event in self.state.events[-50:]],
            "liveReady": self.state.live_ready,
            "riskStatus": self.state.risk_status,
            "requires": self.requirements(),
            "account": self.state.account,
            "risk": asdict(self.risk.snapshot(self.state.open_orders, self.portfolio, mark)),
            "desk": {
                "orderAgeSeconds": max(0.0, time.time() - self.state.last_order_refresh)
                if self.state.last_order_refresh
                else 0.0,
                "orderRefreshSeconds": self.config.order_refresh_seconds,
                "maxMarkMovePct": self.config.max_mark_move_pct,
                "executionMode": self.config.execution_mode,
                "exchangeOrderCount": len(self.state.exchange_order_ids),
                "reconciledFillCount": len(self.state.reconciled_fill_ids),
                "lastReconciliationSeconds": max(0.0, time.time() - self.state.last_reconciliation)
                if self.state.last_reconciliation
                else 0.0,
            },
        }

    def _refresh_live_status(self) -> None:
        try:
            adapter = self._live_adapter()
            mark = adapter.latest_price(self.config.symbol)
            account = self._account_snapshot(adapter, mark)
            with self._lock:
                self.state.mark_price = mark
                self.state.account = account
                self.state.risk_status = "live data ready" if self.config.live_enabled else "live dry-run"
                self.state.last_mark_price = mark
                if not self._live_baseline_initialized:
                    self.harvester = self._build_harvester(mark)
                    self.risk = RiskManager(self.config, self.portfolio.equity(mark))
                    self._live_baseline_initialized = True
                    self._event("info", f"live baseline initialized at {mark}")
        except Exception as error:  # noqa: BLE001
            with self._lock:
                self.state.risk_status = "live data error"
                self._event("error", str(error))

    def _paper_tick(self) -> None:
        candle = self._paper_candles[self._paper_index % len(self._paper_candles)]
        with self._lock:
            self.state.mark_price = candle.close
            if not self.state.open_orders:
                self.state.open_orders = self.harvester.plan_orders(self.portfolio, candle.open)
            fills = self._match_candle(candle, self.state.open_orders)
            for fill in fills:
                self.harvester.record_fill(fill, self.portfolio)
                self.state.fills.append(fill)
            self.state.open_orders = self.harvester.plan_orders(self.portfolio, candle.close)
            self.state.risk_status = "paper"
            self._paper_index += 1

    def _live_tick(self) -> None:
        adapter = self._live_adapter()
        mark = adapter.latest_price(self.config.symbol)
        account = self._account_snapshot(adapter, mark)
        raw_fills = self._fetch_live_fills(adapter)
        with self._lock:
            self._apply_live_fills(raw_fills)
            market_decision = self._market_guard(mark, account)
            if not market_decision.allowed:
                self._cancel_live_orders("market guard cancel")
                self.state.open_orders = []
                self.state.exchange_order_ids = {}
                self.state.mark_price = mark
                self.state.account = account
                self.state.last_mark_price = mark
                self.state.risk_status = market_decision.reason
                self._event("warn", market_decision.reason)
                return
            if not self._live_baseline_initialized:
                self.harvester = self._build_harvester(mark)
                self.risk = RiskManager(self.config, self.portfolio.equity(mark))
                self._live_baseline_initialized = True
                self._event("info", f"live baseline initialized at {mark}")
            self.state.mark_price = mark
            self.state.account = account
            self.state.last_mark_price = mark
            if self.state.open_orders and self._open_orders_stale():
                self._cancel_live_orders("stale grid cancel")
                self._event("info", "refreshing stale live grid")
                self.state.open_orders = []
                self.state.exchange_order_ids = {}
            orders = self.harvester.plan_orders(self.portfolio, mark)
            decision = self.risk.check_batch(orders, self.portfolio, mark)
            if not decision.allowed:
                self._cancel_live_orders("risk guard cancel")
                self.state.open_orders = []
                self.state.exchange_order_ids = {}
                self.state.risk_status = decision.reason
                self._event("warn", decision.reason)
                return
            if self.state.open_orders:
                self.state.risk_status = f"{len(self.state.open_orders)} live orders resting"
                return
            if self.config.execution_mode == "observe":
                self.state.open_orders = []
                self.state.risk_status = "observe mode: market data only"
                return
            if self.config.live_enabled:
                submitted = adapter.place_orders(orders)
                self.state.open_orders = orders
                self.state.exchange_order_ids = {
                    order.local_order_id: order.exchange_order_id
                    for order in submitted
                    if order.exchange_order_id
                }
                self.state.last_order_refresh = time.time()
                self.state.risk_status = f"submitted {len(submitted)} live orders"
                self._event("info", f"submitted {len(submitted)} Hyperliquid orders")
            else:
                self.state.open_orders = orders
                self.state.last_order_refresh = time.time()
                self.state.risk_status = "live dry-run: missing confirmation or keys"

    def _live_adapter(self) -> HyperliquidAdapter:
        if self._adapter is None:
            self._adapter = HyperliquidAdapter(self.config)
            self._event("info", "Hyperliquid adapter initialized")
        return self._adapter

    def _account_snapshot(self, adapter: HyperliquidAdapter, mark: float) -> dict:
        if not self.config.account_address:
            return {}
        user_state = adapter.user_state()
        spot_state = adapter.spot_user_state()
        vaults = adapter.vault_equities()
        margin = user_state.get("marginSummary", {})
        position_size = 0.0
        position_value = 0.0
        coin = self.config.symbol.split("-", 1)[0].upper()
        for item in user_state.get("assetPositions", []):
            position = item.get("position", {})
            if position.get("coin") == coin:
                position_size = float(position.get("szi", 0) or 0)
                position_value = position_size * mark
                break
        spot_balances = []
        spot_usdc = 0.0
        for balance in spot_state.get("balances", []):
            coin = str(balance.get("coin", ""))
            total = float(balance.get("total", 0) or 0)
            hold = float(balance.get("hold", 0) or 0)
            if total or hold:
                spot_balances.append({"coin": coin, "total": total, "hold": hold})
            if coin.upper() == "USDC":
                spot_usdc += total
        perp_value = float(margin.get("accountValue", 0) or 0)
        withdrawable = float(user_state.get("withdrawable", 0) or 0)
        return {
            "accountValue": perp_value,
            "totalMarginUsed": float(margin.get("totalMarginUsed", 0) or 0),
            "withdrawable": withdrawable,
            "positionSize": position_size,
            "positionValue": position_value,
            "spotUsdc": spot_usdc,
            "spotBalances": spot_balances,
            "vaultCount": len(vaults),
            "displayValue": perp_value + spot_usdc,
        }

    def _market_guard(self, mark: float, account: dict) -> RiskDecision:
        previous = self.state.last_mark_price or mark
        move_pct = abs(mark - previous) / previous if previous > 0 else 0.0
        if move_pct > self.config.max_mark_move_pct:
            return RiskDecision(False, f"market shock guard: mark moved {move_pct:.2%}")
        account_value = float(account.get("displayValue", 0) or 0)
        if self.config.min_account_value and account_value < self.config.min_account_value:
            return RiskDecision(False, "account value below minimum")
        position_value = abs(float(account.get("positionValue", 0) or 0))
        if position_value > self.config.max_position_value:
            return RiskDecision(False, "position exposure exceeds limit")
        return RiskDecision(True)

    def _fetch_live_fills(self, adapter: HyperliquidAdapter) -> list[dict]:
        if not self.state.exchange_order_ids:
            return []
        try:
            fills = adapter.fills(self.config.symbol)
        except NotImplementedError:
            return []
        except Exception as error:  # noqa: BLE001
            self._event("warn", f"fill reconciliation skipped: {error}")
            return []
        return fills if isinstance(fills, list) else []

    def _apply_live_fills(self, raw_fills: list[dict]) -> None:
        if not raw_fills or not self.state.exchange_order_ids:
            return

        orders_by_exchange_id = {
            exchange_order_id: order
            for order in self.state.open_orders
            if (exchange_order_id := self.state.exchange_order_ids.get(order.order_id))
        }
        filled_order_ids: set[str] = set()
        reconciled = 0
        for raw_fill in raw_fills:
            fill_id = self._raw_fill_id(raw_fill)
            if fill_id in self.state.reconciled_fill_ids:
                continue
            exchange_order_id = str(raw_fill.get("oid") or raw_fill.get("orderId") or "")
            order = orders_by_exchange_id.get(exchange_order_id)
            if order is None:
                continue
            fill = self._live_fill_from_raw(raw_fill, order)
            self.harvester.record_fill(fill, self.portfolio)
            self.state.fills.append(fill)
            self.state.reconciled_fill_ids.add(fill_id)
            self.state.exchange_order_ids.pop(order.order_id, None)
            filled_order_ids.add(order.order_id)
            reconciled += 1

        if reconciled:
            self.state.open_orders = [
                order for order in self.state.open_orders if order.order_id not in filled_order_ids
            ]
            self.state.last_reconciliation = time.time()
            self._event("info", f"reconciled {reconciled} exchange fills")

    def _raw_fill_id(self, raw_fill: dict) -> str:
        if raw_fill.get("hash"):
            return str(raw_fill["hash"])
        return ":".join(
            str(raw_fill.get(key, ""))
            for key in ("oid", "time", "side", "px", "sz")
        )

    def _live_fill_from_raw(self, raw_fill: dict, order: Order) -> Fill:
        side = str(raw_fill.get("side") or order.side.value).upper()
        mapped_side = OrderSide.BUY if side in {"B", "BUY"} else OrderSide.SELL
        price = float(raw_fill.get("px") or raw_fill.get("price") or order.price)
        quantity = float(raw_fill.get("sz") or raw_fill.get("quantity") or order.quantity)
        fee = abs(float(raw_fill.get("fee") or 0))
        timestamp = str(raw_fill.get("time") or raw_fill.get("timestamp") or time.time())
        return Fill(
            order_id=order.order_id,
            symbol=order.symbol,
            side=mapped_side,
            price=price,
            quantity=quantity,
            fee=fee,
            timestamp=timestamp,
            level_id=order.level_id,
        )

    def _open_orders_stale(self) -> bool:
        if not self.state.last_order_refresh:
            return False
        return time.time() - self.state.last_order_refresh > self.config.order_refresh_seconds

    def _cancel_live_orders(self, reason: str) -> None:
        if not self.config.live_enabled or not self.state.exchange_order_ids:
            return
        adapter = self._live_adapter()
        order_ids = list(self.state.exchange_order_ids.values())
        adapter.cancel_orders(order_ids)
        self._event("warn", f"{reason}: cancelled {len(order_ids)} exchange orders")

    def _match_candle(self, candle: Candle, orders: list[Order]) -> list[Fill]:
        fills: list[Fill] = []
        for order in orders:
            hit = candle.low <= order.price if order.side is OrderSide.BUY else candle.high >= order.price
            if not hit:
                continue
            fee = order.notional * self.config.fee_rate
            fills.append(
                Fill(
                    order_id=order.order_id,
                    symbol=order.symbol,
                    side=order.side,
                    price=order.price,
                    quantity=order.quantity,
                    fee=fee,
                    timestamp=candle.timestamp,
                    level_id=order.level_id,
                )
            )
        return fills

    def _load_paper_candles(self) -> list[Candle]:
        path = Path(__file__).resolve().parents[2] / "examples" / "sample_prices.csv"
        return load_candles(path)

    def _build_harvester(self, center_price: float) -> LiquidityHarvester:
        return LiquidityHarvester(
            LiquidityHarvesterConfig(
                symbol=self.config.symbol,
                center_price=center_price,
                spacing_pct=self.config.spacing_pct,
                levels_each_side=self.config.levels_each_side,
                order_quote_size=self.config.order_quote_size,
                fee_rate=self.config.fee_rate,
            )
        )

    def _event(self, level: str, message: str) -> None:
        self.state.events.append(RuntimeEvent(time.time(), level, message))
        print(f"{level.upper()}: {message}", flush=True)
        self.state.events = self.state.events[-200:]


class JsonEncoder(json.JSONEncoder):
    def default(self, obj):  # noqa: ANN001, ANN201
        if hasattr(obj, "value"):
            return obj.value
        return super().default(obj)

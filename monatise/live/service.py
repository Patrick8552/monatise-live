from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from monatise.adapters.hyperliquid import HyperliquidAdapter
from monatise.core.models import Candle, Fill, Order, OrderSide, Portfolio
from monatise.live.config import RuntimeConfig
from monatise.live.risk import RiskManager
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
        with self._lock:
            self.state.running = False
            self.state.risk_status = "stopped"
            self._event("warn", "kill switch activated")
            return self._snapshot_unlocked()

    def snapshot(self) -> dict:
        with self._lock:
            return self._snapshot_unlocked()

    def requirements(self) -> list[str]:
        missing = []
        if self.config.mode == "live":
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
        }

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
        with self._lock:
            if not self._live_baseline_initialized:
                self.harvester = self._build_harvester(mark)
                self.risk = RiskManager(self.config, self.portfolio.equity(mark))
                self._live_baseline_initialized = True
                self._event("info", f"live baseline initialized at {mark}")
            self.state.mark_price = mark
            orders = self.harvester.plan_orders(self.portfolio, mark)
            decision = self.risk.check_batch(orders, self.portfolio, mark)
            if not decision.allowed:
                self.state.open_orders = []
                self.state.risk_status = decision.reason
                self._event("warn", decision.reason)
                return
            if self.config.live_enabled:
                submitted = adapter.place_orders(orders)
                self.state.open_orders = orders
                self.state.risk_status = f"submitted {len(submitted)} live orders"
                self._event("info", f"submitted {len(submitted)} Hyperliquid orders")
            else:
                self.state.open_orders = orders
                self.state.risk_status = "live dry-run: missing confirmation or keys"

    def _live_adapter(self) -> HyperliquidAdapter:
        if self._adapter is None:
            self._adapter = HyperliquidAdapter(self.config)
            self._event("info", "Hyperliquid adapter initialized")
        return self._adapter

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
        self.state.events = self.state.events[-200:]


class JsonEncoder(json.JSONEncoder):
    def default(self, obj):  # noqa: ANN001, ANN201
        if hasattr(obj, "value"):
            return obj.value
        return super().default(obj)

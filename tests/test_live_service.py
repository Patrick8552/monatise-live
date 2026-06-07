import monatise.live.service as service_module
from monatise.adapters.hyperliquid import HyperliquidAdapter, SubmittedOrder
from monatise.live.config import LIVE_CONFIRMATION, RuntimeConfig
from monatise.live.service import TradingService


class FakeMarketAdapter:
    def latest_price(self, symbol: str) -> float:
        assert symbol == "BTC"
        return 63_816.5


class FakeExecutionAdapter:
    def __init__(self) -> None:
        self.cancelled: list[str] = []
        self.raw_fills: list[dict] = []
        self.submitted = 0

    def latest_price(self, symbol: str) -> float:
        assert symbol == "BTC"
        return 100.0 + self.submitted

    def user_state(self) -> dict:
        return {"marginSummary": {"accountValue": "10000"}, "assetPositions": [], "withdrawable": "10000"}

    def spot_user_state(self) -> dict:
        return {"balances": [{"coin": "USDC", "total": "1000", "hold": "0"}]}

    def vault_equities(self) -> list[dict]:
        return []

    def place_orders(self, orders) -> list[SubmittedOrder]:  # noqa: ANN001
        self.submitted += 1
        return [
            SubmittedOrder(order.order_id, str(9000 + index + self.submitted * 100), {"ok": True})
            for index, order in enumerate(orders)
        ]

    def cancel_orders(self, order_ids: list[str]) -> None:
        self.cancelled.extend(order_ids)

    def fills(self, symbol: str) -> list[dict]:
        assert symbol == "BTC"
        return self.raw_fills


def test_live_tick_initializes_risk_baseline_from_live_mark() -> None:
    service = TradingService(
        RuntimeConfig(
            mode="live",
            network="mainnet",
            symbol="BTC",
            max_daily_loss=100,
            max_base_inventory=1,
        )
    )
    service._adapter = FakeMarketAdapter()

    service._live_tick()
    snapshot = service.snapshot()

    assert snapshot["markPrice"] == 63_816.5
    assert snapshot["riskStatus"] == "live dry-run"
    assert "max daily loss reached" not in [event["message"] for event in snapshot["events"]]
    assert snapshot["executionMode"] == "dry_run"
    assert "risk" in snapshot
    assert snapshot["risk"]["max_daily_loss_pct"] > 0


def test_live_snapshot_exposes_readiness_checklist() -> None:
    service = TradingService(RuntimeConfig(mode="live", network="mainnet", symbol="BTC"))

    snapshot = service.snapshot()
    readiness = {item["label"]: item for item in snapshot["readiness"]}

    assert readiness["Execution mode"]["ok"] is False
    assert readiness["Order placement flag"]["ok"] is False
    assert readiness["Server session guard"]["ok"] is True
    assert "MONATISE_EXECUTION_MODE=live" in snapshot["requires"]


def test_market_shock_guard_blocks_fast_mark_move() -> None:
    service = TradingService(
        RuntimeConfig(
            mode="live",
            network="testnet",
            symbol="BTC",
            max_mark_move_pct=0.01,
        )
    )
    service.state.last_mark_price = 100.0

    decision = service._market_guard(103.0, {})

    assert not decision.allowed
    assert "market shock guard" in decision.reason


def test_live_start_blocks_forex_session_break_guard() -> None:
    original_guard = service_module.forex_session_break_guard
    service_module.forex_session_break_guard = lambda symbol, guard_minutes=60: {
        "active": True,
        "message": "forex session-break guard: EURUSD is 20m before London close",
    }
    try:
        service = TradingService(RuntimeConfig(mode="live", symbol="EURUSD"))

        snapshot = service.start()

        assert not snapshot["running"]
        assert snapshot["riskStatus"] == "forex session-break guard: EURUSD is 20m before London close"
        assert snapshot["sessionGuard"]["active"]
    finally:
        service_module.forex_session_break_guard = original_guard


def test_live_start_blocks_gold_outside_london_when_rule_enabled() -> None:
    original_forex_guard = service_module.forex_session_break_guard
    original_commodity_guard = service_module.commodity_london_guard
    service_module.forex_session_break_guard = lambda symbol, guard_minutes=60: {"active": False, "symbol": symbol}
    service_module.commodity_london_guard = lambda symbol: {
        "active": True,
        "message": "commodity session guard: GOLD live grid orders are limited to the London session",
    }
    try:
        service = TradingService(RuntimeConfig(mode="live", symbol="GOLD", london_commodity_only=True))

        snapshot = service.start()

        assert not snapshot["running"]
        assert snapshot["riskStatus"] == "commodity session guard: GOLD live grid orders are limited to the London session"
        assert snapshot["sessionGuard"]["active"]
    finally:
        service_module.forex_session_break_guard = original_forex_guard
        service_module.commodity_london_guard = original_commodity_guard


def test_stale_live_grid_cancels_exchange_orders_before_replace() -> None:
    service = TradingService(
        RuntimeConfig(
            mode="live",
            execution_mode="live",
            allow_live_orders=True,
            live_confirmation=LIVE_CONFIRMATION,
            account_address="0xabc",
            secret_key="secret",
            order_refresh_seconds=0.01,
            order_quote_size=10,
            max_order_notional=10,
            max_total_notional=100,
            max_position_value=100_000,
            max_base_inventory=10,
        )
    )
    adapter = FakeExecutionAdapter()
    service._adapter = adapter

    service._live_tick()
    first_ids = set(service.state.exchange_order_ids.values())
    service.state.last_order_refresh -= 1
    service._live_tick()

    assert first_ids
    assert first_ids.issubset(set(adapter.cancelled))
    assert adapter.submitted == 2


def test_live_tick_cancels_orders_during_forex_session_break_guard() -> None:
    original_guard = service_module.forex_session_break_guard
    guard_calls = {"count": 0}

    def guard(symbol: str, guard_minutes: int = 60) -> dict:
        guard_calls["count"] += 1
        if guard_calls["count"] == 1:
            return {"active": False, "symbol": symbol}
        return {
            "active": True,
            "message": "forex session-break guard: EURUSD is 15m before London close",
        }

    service_module.forex_session_break_guard = guard
    try:
        service = TradingService(
            RuntimeConfig(
                mode="live",
                execution_mode="live",
                allow_live_orders=True,
                live_confirmation=LIVE_CONFIRMATION,
                account_address="0xabc",
                secret_key="secret",
                order_quote_size=10,
                max_order_notional=10,
                max_total_notional=100,
                max_position_value=100_000,
                max_base_inventory=10,
            )
        )
        adapter = FakeExecutionAdapter()
        service._adapter = adapter

        service._live_tick()
        first_ids = set(service.state.exchange_order_ids.values())
        service._live_tick()

        assert first_ids
        assert first_ids.issubset(set(adapter.cancelled))
        assert not service.state.open_orders
        assert service.state.risk_status == "forex session-break guard: EURUSD is 15m before London close"
    finally:
        service_module.forex_session_break_guard = original_guard


def test_live_tick_reconciles_exchange_fills_once() -> None:
    service = TradingService(
        RuntimeConfig(
            mode="live",
            execution_mode="live",
            allow_live_orders=True,
            live_confirmation=LIVE_CONFIRMATION,
            account_address="0xabc",
            secret_key="secret",
            order_quote_size=10,
            max_order_notional=10,
            max_total_notional=100,
            max_position_value=100_000,
            max_base_inventory=10,
        )
    )
    adapter = FakeExecutionAdapter()
    service._adapter = adapter

    service._live_tick()
    order = service.state.open_orders[0]
    exchange_order_id = service.state.exchange_order_ids[order.order_id]
    adapter.raw_fills = [
        {
            "coin": "BTC",
            "fee": "0.004",
            "hash": "fill-hash-1",
            "oid": exchange_order_id,
            "px": str(order.price),
            "side": "B" if order.side.value == "buy" else "A",
            "sz": str(order.quantity),
            "time": 1780794000,
        }
    ]

    service._live_tick()
    fill_count = len(service.state.fills)
    service._live_tick()

    assert fill_count == 1
    assert len(service.state.fills) == 1
    assert order.order_id not in service.state.exchange_order_ids
    assert service.state.last_reconciliation > 0


def test_hyperliquid_order_values_are_rounded_for_wire_format() -> None:
    adapter = HyperliquidAdapter.__new__(HyperliquidAdapter)

    assert adapter._order_quantity(0.0041410259) == 0.00414
    assert adapter._order_price(61919.54321) == 61919.5


def test_hyperliquid_extracts_exchange_order_id() -> None:
    adapter = HyperliquidAdapter.__new__(HyperliquidAdapter)
    response = {"response": {"data": {"statuses": [{"resting": {"oid": 12345}}]}}}

    assert adapter._exchange_order_id(response) == "12345"

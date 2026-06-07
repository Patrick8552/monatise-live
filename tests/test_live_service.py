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


def test_hyperliquid_order_values_are_rounded_for_wire_format() -> None:
    adapter = HyperliquidAdapter.__new__(HyperliquidAdapter)

    assert adapter._order_quantity(0.0041410259) == 0.00414
    assert adapter._order_price(61919.54321) == 61919.5


def test_hyperliquid_extracts_exchange_order_id() -> None:
    adapter = HyperliquidAdapter.__new__(HyperliquidAdapter)
    response = {"response": {"data": {"statuses": [{"resting": {"oid": 12345}}]}}}

    assert adapter._exchange_order_id(response) == "12345"

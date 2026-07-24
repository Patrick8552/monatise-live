from monatise.adapters.hyperliquid import HyperliquidAdapter
from monatise.live.config import RuntimeConfig
from monatise.live.service import TradingService


class FakeMarketAdapter:
    def latest_price(self, symbol: str) -> float:
        assert symbol == "BTC"
        return 63_816.5


def test_live_tick_initializes_risk_baseline_from_live_mark() -> None:
    service = TradingService(
        RuntimeConfig(
            mode="live",
            network="mainnet",
            symbol="BTC",
            signal_session_window="always",
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
    assert snapshot["executionMode"] == "disabled"
    assert "risk" in snapshot
    assert snapshot["risk"]["max_daily_loss_pct"] > 0
    assert snapshot["signalStatus"]["state"] == "generated"
    assert snapshot["signalStatus"]["count"] == len(snapshot["signals"])
    assert snapshot["signals"]
    assert snapshot["signals"][0]["action"] in {"BUY", "SELL"}
    assert snapshot["signals"][0]["state"] == "planned"
    assert snapshot["wealthCommand"]["score"] <= 100
    assert snapshot["wealthCommand"]["posture"] in {"Offensive", "Selective", "Cautious", "Defensive"}


def test_live_snapshot_exposes_readiness_checklist() -> None:
    service = TradingService(RuntimeConfig(mode="live", network="mainnet", symbol="BTC", signal_session_window="always"))

    snapshot = service.snapshot()
    readiness = {item["label"]: item for item in snapshot["readiness"]}

    assert readiness["Execution mode"]["ok"] is False
    assert readiness["Order placement flag"]["ok"] is False
    assert readiness["Server session guard"]["ok"] is True
    assert snapshot["requires"] == ["Execution is globally disabled; analysis remains available"]
    assert snapshot["wealthCommand"]["primaryBlock"]


def test_live_snapshot_generates_planned_signals_before_orders_rest() -> None:
    service = TradingService(
        RuntimeConfig(
            mode="live",
            network="mainnet",
            symbol="BTC",
            signal_session_window="always",
            max_daily_loss=100,
            max_base_inventory=1,
        )
    )
    service._adapter = FakeMarketAdapter()

    snapshot = service.snapshot()

    assert not snapshot["running"]
    assert snapshot["openOrders"] == []
    assert snapshot["signalStatus"]["state"] == "generated"
    assert snapshot["signals"]
    assert {signal["state"] for signal in snapshot["signals"]} == {"planned"}


def test_live_snapshot_trims_planned_signals_to_total_risk_cap() -> None:
    service = TradingService(
        RuntimeConfig(
            mode="live",
            network="mainnet",
            symbol="BTC",
            signal_session_window="always",
            order_quote_size=25,
            max_order_notional=25,
            max_total_notional=150,
            max_daily_loss=100,
            max_base_inventory=1,
        )
    )
    service._adapter = FakeMarketAdapter()

    snapshot = service.snapshot()

    assert snapshot["signalStatus"]["state"] == "generated"
    assert 1 <= len(snapshot["signals"]) <= 6
    assert sum(signal["notional"] for signal in snapshot["signals"]) <= 150


def test_client_drawdown_percentage_sets_daily_loss_limit() -> None:
    service = TradingService(
        RuntimeConfig(mode="paper", leverage=10, max_daily_loss=1, max_daily_loss_pct=0.12, max_total_notional=150)
    )

    snapshot = service.snapshot()

    assert snapshot["risk"]["max_daily_loss_pct"] == 0.12
    assert snapshot["risk"]["max_daily_loss"] == snapshot["risk"]["starting_equity"] * 0.12
    assert snapshot["risk"]["leverage"] == 10
    assert snapshot["risk"]["max_grid_margin"] == 15
    assert snapshot["tradingRules"]["maxDailyLossPct"] == 0.12


def test_market_shock_guard_blocks_fast_mark_move() -> None:
    service = TradingService(
        RuntimeConfig(
            mode="live",
            network="testnet",
            symbol="BTC",
            signal_session_window="always",
            max_mark_move_pct=0.01,
        )
    )
    service.state.last_mark_price = 100.0

    decision = service._market_guard(103.0, {})

    assert not decision.allowed
    assert "market shock guard" in decision.reason


def test_live_start_remains_disabled_when_signal_window_is_always() -> None:
    service = TradingService(RuntimeConfig(mode="live", symbol="BTC", signal_session_window="always"))

    snapshot = service.start()

    service.stop()
    assert not snapshot["running"]
    assert not snapshot["sessionGuard"]["active"]


def test_hyperliquid_order_values_are_rounded_for_wire_format() -> None:
    adapter = HyperliquidAdapter.__new__(HyperliquidAdapter)

    assert adapter._order_quantity(0.0041410259) == 0.00414
    assert adapter._order_price(61919.54321) == 61919.5
    assert adapter._order_price(0.123456789, "DOGE") == 0.123457


def test_hyperliquid_extracts_exchange_order_id() -> None:
    adapter = HyperliquidAdapter.__new__(HyperliquidAdapter)
    response = {"response": {"data": {"statuses": [{"resting": {"oid": 12345}}]}}}

    assert adapter._exchange_order_id(response) == "12345"

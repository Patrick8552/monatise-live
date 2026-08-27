from pathlib import Path


BRIDGE_SOURCE = Path(__file__).parents[1] / "mt5" / "Experts" / "MonatiseFTMOBridge.mq5"


def test_mt5_bridge_enforces_expiry_price_volume_and_broker_symbol_constraints():
    source = BRIDGE_SOURCE.read_text(encoding="utf-8")

    assert '#property version   "1.06"' in source
    assert 'InpSymbols                = "XAUUSD,US100.cash,AAPL,EURUSD,GBPUSD,USDJPY,USDCHF,AUDUSD,NZDUSD,USDCAD"' in source
    assert "BTCUSD" not in source.split("input string InpSymbols", 1)[1].split(";", 1)[0]
    assert "InpRiskFraction           = 0.03" in source
    assert "InpMaximumRiskAmount" not in source
    assert "InpMaximumDailyLossAmount" not in source
    assert "MathMin(InpRiskFraction, 0.03)" in source
    assert 'JsonString(payload, "expires_epoch")' in source
    assert "SYMBOL_TRADE_MODE_FULL" in source
    assert "SYMBOL_VOLUME_MIN" in source and "SYMBOL_VOLUME_MAX" in source and "SYMBOL_VOLUME_STEP" in source
    assert "SYMBOL_TRADE_STOPS_LEVEL" in source and "SYMBOL_TRADE_FREEZE_LEVEL" in source
    assert "InpMaximumDeviationPoints" in source
    assert "Trade.SetDeviationInPoints" in source
    assert "ORDER_TIME_SPECIFIED" in source


def test_mt5_bridge_preserves_idempotency_and_returns_execution_evidence():
    source = BRIDGE_SOURCE.read_text(encoding="utf-8")

    assert 'string comment = "MNT:" + StringSubstr(command_id, 0, 16)' in source
    assert 'JournalAppend(command_id, "broker_uncertain"' in source
    assert "AcknowledgeEvidence(" in source
    for field in (
        "requested_price", "fill_price", "slippage", "executed_volume",
        "executed_stop_loss", "executed_take_profit", "broker_observed_at",
    ):
        assert f'\\"{field}\\"' in source


def test_mt5_heartbeat_contains_authoritative_ftmo_execution_snapshot():
    source = BRIDGE_SOURCE.read_text(encoding="utf-8")

    for field in (
        "bid", "ask", "point", "tick_size", "tick_value_loss", "tick_value_profit",
        "contract_size", "volume_min", "volume_max", "volume_step", "stops_level",
        "freeze_level", "trade_mode", "free_margin", "positions", "orders",
    ):
        assert f'\\"{field}\\"' in source


def test_mt5_quote_time_contract_separates_broker_time_from_utc_and_rejects_skew():
    source = BRIDGE_SOURCE.read_text(encoding="utf-8")

    assert "datetime observed_utc = TimeGMT()" in source
    assert "BrokerUtcOffsetSeconds()" in source
    assert "BrokerTimeToUtc(tick.time)" in source
    for field in (
        "observed_at_utc", "quote_observed_at_utc", "broker_time",
        "broker_time_offset", "terminal_local_time",
    ):
        assert f'\\"{field}\\"' in source
    assert "quote_age_seconds < -1 || quote_age_seconds > 5" in source
    assert "command_quote_age < -1 || command_quote_age > 5" in source
    assert '"timestamp":"" + IsoTime((datetime)(tick.time_msc / 1000))' not in source

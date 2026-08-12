from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from monatise.adapters.coinglass_production import CoinGlassProductionAdapter
from monatise.application.dynamic_analysis import finalize_dynamic_analysis
from monatise.application.production import ProductionASGI
from monatise.application.production_analysis import build_production_analysis_run
from monatise.core.models import Candle
from monatise.engines.market_data.models import DataQuality, DataStatus, MarketSnapshot


def adapter(supported, markets):
    instance = CoinGlassProductionAdapter(lambda: "secret", maximum_attempts=1, requests_per_second=1000)
    instance.supported_futures_coins = lambda: tuple(supported)
    instance.supported_exchange_pairs = lambda: tuple(
        (row["exchange_name"], row["instrument_id"], row.get("base_asset", ""), row.get("quote_asset", ""))
        for row in markets
    )
    instance._fetch = lambda dataset, symbol, **kwargs: list(markets)
    return instance


def test_wood_style_symbol_resolves_with_mocked_coinglass_data():
    instance = adapter(["BTC", "WOOD"], [{
        "exchange_name": "Bybit", "instrument_id": "WOODUSDT", "base_asset": "WOOD",
        "quote_asset": "USDT", "current_price": "0.42", "volume_usd": "2500000",
    }])
    resolved = instance.resolve_futures_asset("wood/usdt")
    assert resolved.base_asset == "WOOD"
    assert resolved.instrument == "WOODUSDT"
    assert resolved.exchange == "Bybit"
    assert resolved.source.startswith("CoinGlass futures")


def test_non_binance_valid_market_is_selected():
    instance = adapter(["WOOD"], [{
        "exchange_name": "OKX", "instrument_id": "WOOD-USDT", "base_asset": "WOOD",
        "quote_asset": "USDT", "current_price": 1.0, "volume_usd": 900000,
    }])
    resolved = instance.resolve_futures_asset("WOOD")
    assert (resolved.exchange, resolved.instrument) == ("OKX", "WOOD-USDT")
    assert instance._dataset_params("price_history", "WOOD")["exchange"] == "OKX"
    assert instance._dataset_params("order_book", "WOOD")["exchange_list"] == "OKX"


@pytest.mark.parametrize("symbol", ["EURUSD", "../../BTC", "USD", "", "BTC$USDT"])
def test_malformed_forex_and_unsupported_inputs_are_rejected(symbol):
    with pytest.raises(ValueError):
        adapter(["BTC"], []).resolve_futures_asset(symbol)


def test_ambiguous_market_without_activity_is_rejected():
    rows = [
        {"exchange_name": "A", "instrument_id": "WOODUSDT", "base_asset": "WOOD", "quote_asset": "USDT", "current_price": 1},
        {"exchange_name": "B", "instrument_id": "WOODUSDC", "base_asset": "WOOD", "quote_asset": "USDC", "current_price": 1},
    ]
    with pytest.raises(ValueError, match="ambiguous"):
        adapter(["WOOD"], rows).resolve_futures_asset("WOOD")


def test_unavailable_ticker_is_rejected_before_market_resolution():
    with pytest.raises(ValueError, match="does not list"):
        adapter(["BTC"], []).resolve_futures_asset("WOOD")


def _quality_result(*, candle_count=140, status=DataStatus.READY, stale=False, derivatives=None):
    now = datetime.now(timezone.utc)
    candles = tuple(Candle((now - timedelta(hours=candle_count-index)).isoformat(), 1, 1.1, .9, 1, 10000) for index in range(candle_count))
    latest_at = now - timedelta(hours=5) if stale else now
    quality = DataQuality(status, "coinglass", now, latest_at, (now-latest_at).total_seconds(), ())
    market = MarketSnapshot("WOOD", "1h", 1.0, candles, quality, derivatives or {"funding_rate": None, "open_interest": 12})
    result = SimpleNamespace(context=SimpleNamespace(outputs={"market_data": market}))
    asset = SimpleNamespace(to_dict=lambda: {"base_asset": "WOOD"}, supported_coins_observed_at=now.isoformat(), market_observed_at=now.isoformat())
    return result, asset


def test_missing_optional_derivatives_are_labeled_unavailable():
    result, asset = _quality_result()
    output = finalize_dynamic_analysis({"classification": "no_trade", "entry_confirmation_status": "pending"}, result, asset)
    assert output["evidence"]["derivatives"]["funding_rate"]["status"] == "unavailable"
    assert any("funding_rate" in item for item in output["data_quality"]["warnings"])


def test_confirmed_trend_has_planned_zone_risk_reward_and_expiry_not_market_entry():
    result, asset = _quality_result()
    output = finalize_dynamic_analysis({"classification": "trend", "direction": "long", "interval": "1h", "entry_confirmation_status": "confirmed"}, result, asset)
    assert output["data_quality"]["passed"] is True
    assert output["entry"] is None
    assert output["entry_zone"]["low"] < output["entry_zone"]["high"]
    assert output["invalidation"] is not None and output["targets"]
    assert output["reward_risk"] > 0 and output["expires_at"]


@pytest.mark.parametrize(("count", "status"), [(20, DataStatus.READY), (140, DataStatus.DEGRADED)])
def test_stale_or_insufficient_candles_fail_closed_to_no_trade(count, status):
    result, asset = _quality_result(candle_count=count, status=status)
    output = finalize_dynamic_analysis({"classification": "trend", "direction": "long", "entry": 1, "target": 2, "entry_confirmation_status": "confirmed"}, result, asset)
    assert output["classification"] == "no_trade"
    assert output["data_quality"]["passed"] is False
    assert output["execution_enabled"] is False


class DynamicRuntime:
    def __init__(self):
        self.environment = {"MONATISE_OPENCLAW_TOKEN": "read-secret"}
        self.telegram = None
        self.calls = []
    async def analyse_dynamic_coinglass(self, symbol, **kwargs):
        self.calls.append((symbol, kwargs))
        return {"symbol": symbol, "classification": "no_trade", "execution_enabled": False}


def openclaw(app, token, query="symbol=WOOD&interval=1h", client=("127.0.0.1", 1)):
    messages = []
    async def receive(): return {"type": "http.request", "body": b"", "more_body": False}
    async def send(message): messages.append(message)
    scope = {"type": "http", "method": "GET", "path": "/api/openclaw/status", "query_string": query.encode(), "headers": [(b"authorization", f"Bearer {token}".encode())], "client": client}
    asyncio.run(app(scope, receive, send))
    return messages[0]["status"], json.loads(messages[1]["body"])


def test_dynamic_route_preserves_auth_cache_and_read_only_capabilities():
    runtime = DynamicRuntime(); app = ProductionASGI(runtime)
    assert openclaw(app, "wrong")[0] == 401
    code, payload = openclaw(app, "read-secret")
    assert code == 200 and payload["execution_enabled"] is False
    assert payload["capabilities"]["liveOrders"] is False
    assert payload["capabilities"]["configurationWrites"] is False
    assert payload["capabilities"]["deploymentWrites"] is False
    assert openclaw(app, "read-secret")[1]["cache_hit"] is True
    assert len(runtime.calls) == 1


def test_dynamic_route_is_rate_limited():
    app = ProductionASGI(DynamicRuntime())
    for index in range(12):
        assert openclaw(app, "read-secret", query=f"symbol=COIN{index}&interval=1h", client=("10.0.0.1", 1))[0] == 200
    assert openclaw(app, "read-secret", query="symbol=LAST&interval=1h", client=("10.0.0.1", 1))[0] == 429


def test_core_universe_remains_supported_and_unverified_dynamic_is_rejected():
    for symbol in ("BTC", "ETH", "SOL"):
        assert build_production_analysis_run(symbol).symbol == symbol
    with pytest.raises(ValueError):
        build_production_analysis_run("WOOD")
    assert build_production_analysis_run("WOOD", verified_dynamic=True).symbol == "WOOD"

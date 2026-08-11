import asyncio
from types import SimpleNamespace

import pytest

from monatise.application.deployment import OrchestrationRuntime


def test_price_change_parser_accepts_coinglass_24h_shape():
    assert OrchestrationRuntime._price_change_24h({"price_change_percent_24h": "18.25"}) == 18.25
    assert OrchestrationRuntime._price_change_24h({"price_change_24h": -21}) == -21.0


def test_price_change_parser_fails_closed():
    assert OrchestrationRuntime._price_change_24h({"price_change_percent_24h": "unknown"}) is None
    assert OrchestrationRuntime._price_change_24h({}) is None


def test_coinglass_supported_coin_normalization():
    adapter = SimpleNamespace()
    from monatise.adapters.coinglass_production import CoinGlassProductionAdapter
    instance = object.__new__(CoinGlassProductionAdapter)
    instance.dashboard_query = lambda path, params: {"code": "0", "data": ["btc", "NEW", "BTC", ""]}
    assert instance.supported_futures_coins() == ("BTC", "NEW")


class _AlertRedis:
    def __init__(self):
        self.values = {}

    async def set(self, key, value, **kwargs):
        if kwargs.get("nx") and key in self.values:
            return False
        self.values[key] = (value, kwargs.get("ex"))
        return True

    async def delete(self, key):
        self.values.pop(key, None)


def test_coin_alert_is_only_deduplicated_after_delivery():
    class Telegram:
        async def coin_discovery_notification(self, message):
            assert message == "new coin"

    runtime = object.__new__(OrchestrationRuntime)
    runtime.environment = {"MONATISE_REDIS_NAMESPACE": "test"}
    runtime.redis = _AlertRedis()
    runtime.telegram = Telegram()

    assert asyncio.run(runtime._deliver_coin_alert("new:ABC", "new coin", ttl_seconds=604800)) is True
    assert runtime.redis.values["test:coin-alert:new:ABC"] == ("delivered", 604800)
    assert asyncio.run(runtime._deliver_coin_alert("new:ABC", "new coin", ttl_seconds=604800)) is False


def test_failed_coin_alert_releases_reservation_for_retry():
    class Telegram:
        async def coin_discovery_notification(self, message):
            raise RuntimeError("temporary Telegram failure")

    runtime = object.__new__(OrchestrationRuntime)
    runtime.environment = {"MONATISE_REDIS_NAMESPACE": "test"}
    runtime.redis = _AlertRedis()
    runtime.telegram = Telegram()

    with pytest.raises(RuntimeError, match="temporary Telegram failure"):
        asyncio.run(runtime._deliver_coin_alert("new:ABC", "new coin", ttl_seconds=604800))
    assert "test:coin-alert:new:ABC" not in runtime.redis.values

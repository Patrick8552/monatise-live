import asyncio

from monatise.application.deployment import OrchestrationRuntime
from monatise.application.flashalpha_analysis import build_flashalpha_futures_analysis
from monatise.application.workflows import TelegramNotifier


class Redis:
    def __init__(self): self.values = {}
    async def get(self, key): return self.values.get(key)
    async def set(self, key, value, **kwargs):
        if kwargs.get("nx") and key in self.values: return False
        self.values[key] = value
        return True
    async def delete(self, key): self.values.pop(key, None)


def context(**overrides):
    value = {"source": "FlashAlpha", "symbol": "ES=F", "underlying_price": 6500, "gamma_flip": 6480, "call_wall": 6560, "put_wall": 6420, "net_gex_label": "positive"}
    value.update(overrides)
    return value


def test_futures_analysis_builds_wall_targeted_long_setup():
    result = build_flashalpha_futures_analysis(context())
    assert result["decision"] == "BUY_WATCH"
    assert result["direction"] == "LONG"
    assert result["setup_status"] == "confirmed"
    assert result["stop_loss"] == 6480 and result["target"] == 6560
    assert result["score"] >= 7


def test_futures_analysis_rejects_setup_without_reward_room():
    result = build_flashalpha_futures_analysis(context(call_wall=6510))
    assert result["decision"] == "NO_TRADE"
    assert result["setup_status"] == "reward_risk_below_threshold"


def test_futures_telegram_formatter_is_actionable_but_non_executing():
    message = TelegramNotifier.format_flashalpha_futures_analysis(build_flashalpha_futures_analysis(context()))
    assert "Monatise CME futures setup: ES LONG" in message
    assert "Invalidation / gamma flip" in message
    assert "Target / call wall" in message
    assert "no trade was executed" in message


def test_futures_scanner_publishes_only_qualified_and_dedupes(monkeypatch):
    class Adapter:
        def context(self, symbol):
            return context(symbol=symbol) if symbol.startswith("ES") else context(symbol=symbol, call_wall=6510)
    class Telegram:
        def __init__(self): self.messages = []
        async def stock_analysis_notification(self, message): self.messages.append(message)
    monkeypatch.setattr("monatise.application.deployment.FlashAlphaAdapter.from_env", classmethod(lambda cls: Adapter()))
    runtime = OrchestrationRuntime.__new__(OrchestrationRuntime)
    runtime.redis, runtime.telegram = Redis(), Telegram()
    first = asyncio.run(runtime._analyze_flashalpha_futures(("ES", "NQ"), 3600, "test"))
    second = asyncio.run(runtime._analyze_flashalpha_futures(("ES", "NQ"), 3600, "test"))
    assert first == {"symbols": 2, "analyzed": 2, "published": 1, "failures": []}
    assert second["published"] == 0
    assert len(runtime.telegram.messages) == 1

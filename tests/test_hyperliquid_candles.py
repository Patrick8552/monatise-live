from monatise.adapters.hyperliquid import HyperliquidAdapter, _interval_millis, _parse_candle
from monatise.live.config import RuntimeConfig


class FakeInfo:
    def __init__(self) -> None:
        self.payload = None

    def post(self, path: str, payload: dict) -> list[dict]:
        self.payload = {"path": path, "payload": payload}
        return [
            {"t": 1, "o": "100", "h": "105", "l": "99", "c": "104", "v": "12"},
            {"t": 2, "o": "104", "h": "108", "l": "103", "c": "107", "v": "8"},
        ]


def test_hyperliquid_candle_snapshot_uses_builder_coin_alias() -> None:
    adapter = HyperliquidAdapter.__new__(HyperliquidAdapter)
    adapter.config = RuntimeConfig(network="mainnet")
    adapter.info = FakeInfo()

    candles = adapter.candles("CL", 2, interval="1h")

    assert len(candles) == 2
    assert candles[-1].close == 107
    assert adapter.info.payload["path"] == "/info"
    assert adapter.info.payload["payload"]["type"] == "candleSnapshot"
    assert adapter.info.payload["payload"]["req"]["coin"] == "xyz:CL"
    assert adapter.info.payload["payload"]["req"]["interval"] == "1h"


def test_parse_candle_and_interval_validation() -> None:
    candle = _parse_candle({"T": 123, "o": "10", "h": "12", "l": "9", "c": "11", "v": "2"})

    assert candle.timestamp == "123"
    assert candle.volume == 2
    assert _interval_millis("15m") == 900_000

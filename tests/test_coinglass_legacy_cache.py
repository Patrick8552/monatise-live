from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest

import monatise.adapters.coinglass as coinglass_module
from monatise.adapters.coinglass import CoinGlassAdapter


def _adapter(loader):
    adapter = object.__new__(CoinGlassAdapter)
    adapter._get = loader
    return adapter


def test_exchange_pairs_cache_uses_single_flight_across_concurrent_adapters(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    calls_lock = threading.Lock()

    def load(path, params):
        nonlocal calls
        assert path == "/api/futures/supported-exchange-pairs"
        assert params == {}
        with calls_lock:
            calls += 1
        time.sleep(0.03)
        return {"Binance": [{"base_asset": "BTC", "instrument_id": "BTCUSDT"}]}

    monkeypatch.setattr(CoinGlassAdapter, "_pairs_cache", (0.0, {}))
    adapters = [_adapter(load) for _ in range(8)]
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda adapter: adapter._exchange_pairs(), adapters))

    assert calls == 1
    assert all(result == results[0] for result in results)


def test_exchange_pairs_cache_rejects_an_oversized_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CoinGlassAdapter, "_pairs_cache", (0.0, {}))
    monkeypatch.setattr(coinglass_module, "PAIR_CACHE_MAX_BYTES", 32)
    adapter = _adapter(lambda _path, _params: {"Binance": [{"instrument_id": "BTCUSDT"}]})

    with pytest.raises(RuntimeError, match="payload exceeds 32 byte cache limit"):
        adapter._exchange_pairs()

    assert CoinGlassAdapter._pairs_cache == (0.0, {})

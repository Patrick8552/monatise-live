from __future__ import annotations

from typing import Protocol


class DerivativesDataPort(Protocol):
    """Optional derivatives context supplied by CoinGlass-like adapters.

    Missing fields must be returned as None, never silently converted to zero.
    """

    def derivatives_snapshot(self, symbol: str, interval: str = "1h") -> dict[str, float | None]:
        raise NotImplementedError

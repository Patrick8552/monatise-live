"""Dynamic CoinGlass futures-universe filtering and directional-move ranking."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite, log10
from typing import Any, Iterable


STABLE_BASES = frozenset({"USDT", "USDC", "USDE", "DAI", "FDUSD", "TUSD", "USDP", "PYUSD", "USD1"})
LEVERAGED_SUFFIXES = ("3L", "3S", "5L", "5S", "BULL", "BEAR", "UP", "DOWN")


@dataclass(frozen=True)
class UniverseCandidate:
    symbol: str
    score: float
    direction: str
    reasons: tuple[str, ...]
    volume_usd: float
    open_interest_usd: float
    change_5m: float
    change_15m: float
    change_1h: float
    change_24h: float
    volume_change_15m: float
    open_interest_change_15m: float
    funding_rate: float

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["reasons"] = list(self.reasons)
        return value


def rank_significant_futures_universe(
    supported_coins: Iterable[str],
    rows: Iterable[dict[str, Any]],
    *,
    minimum_volume_usd: float = 5_000_000.0,
    minimum_open_interest_usd: float = 1_000_000.0,
    limit: int = 20,
) -> tuple[UniverseCandidate, ...]:
    supported = {str(item).strip().upper() for item in supported_coins}
    candidates: list[UniverseCandidate] = []
    for row in rows:
        symbol = str(row.get("symbol") or row.get("coin") or row.get("base_asset") or "").strip().upper()
        if symbol not in supported or not _eligible_symbol(symbol):
            continue
        volume = _number(row, "volume_usd", "volume_usd_24h", "volume_24h_usd", "turnover_24h", "total_volume_usd")
        oi = _number(row, "open_interest_usd", "openInterestUsd", "open_interest")
        if volume < minimum_volume_usd or oi < minimum_open_interest_usd:
            continue
        change_5m = _number(row, "price_change_percent_5m", "price_change_5m")
        change_15m = _number(row, "price_change_percent_15m", "price_change_15m")
        change_1h = _number(row, "price_change_percent_1h", "price_change_1h")
        change_24h = _number(row, "price_change_percent_24h", "price_change_24h")
        volume_change_15m = _number(row, "volume_change_percent_15m")
        oi_change_15m = _number(row, "open_interest_change_percent_15m")
        funding_rate = _number(row, "avg_funding_rate_by_oi", "funding_rate")
        acceleration = change_5m * 3.0 + change_15m * 2.0 + change_1h
        directional_votes = sum(1 if value > 0 else -1 if value < 0 else 0 for value in (change_5m, change_15m, change_1h))
        if abs(directional_votes) < 2 or abs(acceleration) < 0.5:
            continue
        direction = "long" if acceleration > 0 else "short"
        liquidity_score = min(4.0, max(0.0, log10(max(volume, 1.0)) - 6.0) + max(0.0, log10(max(oi, 1.0)) - 5.0))
        participation = min(2.0, abs(volume_change_15m) * 0.02 + abs(oi_change_15m) * 0.15)
        momentum_score = min(6.0, abs(acceleration) + min(abs(change_24h), 10.0) * 0.1 + participation)
        score = round(liquidity_score + momentum_score, 3)
        reasons = (
            f"{direction} acceleration across 5m/15m/1h",
            f"24h volume ${volume:,.0f}",
            f"open interest ${oi:,.0f}",
            f"15m volume/OI change {volume_change_15m:+.2f}%/{oi_change_15m:+.2f}%",
        )
        candidates.append(UniverseCandidate(symbol, score, direction, reasons, volume, oi, change_5m, change_15m, change_1h, change_24h, volume_change_15m, oi_change_15m, funding_rate))
    candidates.sort(key=lambda item: (-item.score, -item.volume_usd, item.symbol))
    return tuple(candidates[:max(0, limit)])


def _eligible_symbol(symbol: str) -> bool:
    return bool(symbol) and symbol not in STABLE_BASES and not symbol.endswith(LEVERAGED_SUFFIXES) and symbol.isalnum()


def _number(row: dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = row.get(key)
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if isfinite(number):
            return number
    return 0.0

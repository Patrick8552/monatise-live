"""Canonical FTMO instrument registry used by every production scanner.

The bundled registry is an auditable snapshot of FTMO's public symbols API.
Refreshing is deliberately review-only: newly observed symbols are reported and
must be committed to this file before they can become scanner-eligible.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Iterable
from urllib.request import Request, urlopen


FTMO_SYMBOLS_URL = "https://ftmo.com/wp-json/ftmo/symbols"
REGISTRY_SOURCE = "FTMO public symbols API"
REGISTRY_VERSION = "ftmo-official-2026-08-24"
REGISTRY_VERIFIED_AT = datetime(2026, 8, 24, 12, 30, tzinfo=timezone.utc)
_SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/]*$")


class FTMOAssetClass(StrEnum):
    STOCK = "stock"
    FUTURES_LINKED = "futures_linked_cfd"
    CRYPTO = "crypto"


@dataclass(frozen=True)
class FTMOInstrument:
    asset_class: FTMOAssetClass
    ftmo_symbol: str
    display_name: str
    underlying_symbol: str
    underlying_market: str
    exchange: str
    market_data_provider: str
    provider_symbol: str | None
    futures_symbol: str | None
    micro_futures_symbol: str | None
    market_hours: str
    currency: str
    enabled: bool
    instrument_status: str
    source: str
    registry_version: str
    last_verified_at: datetime

    def __post_init__(self) -> None:
        if not _SYMBOL_PATTERN.fullmatch(self.ftmo_symbol):
            raise ValueError(f"malformed FTMO symbol: {self.ftmo_symbol!r}")
        if not self.display_name.strip() or not self.underlying_symbol.strip():
            raise ValueError(f"missing identity for FTMO symbol {self.ftmo_symbol}")
        if not self.source.strip() or not self.registry_version.strip():
            raise ValueError(f"missing provenance for FTMO symbol {self.ftmo_symbol}")
        if self.last_verified_at.tzinfo is None or self.last_verified_at.utcoffset() is None:
            raise ValueError("last_verified_at must be timezone-aware")
        if self.asset_class is FTMOAssetClass.FUTURES_LINKED and self.enabled and not self.futures_symbol:
            raise ValueError(f"enabled futures-linked symbol has no legitimate futures mapping: {self.ftmo_symbol}")
        if self.asset_class is not FTMOAssetClass.FUTURES_LINKED and (self.futures_symbol or self.micro_futures_symbol):
            raise ValueError(f"non-futures instrument has a futures mapping: {self.ftmo_symbol}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_class": self.asset_class.value,
            "ftmo_symbol": self.ftmo_symbol,
            "display_name": self.display_name,
            "underlying_symbol": self.underlying_symbol,
            "underlying_market": self.underlying_market,
            "exchange": self.exchange,
            "market_data_provider": self.market_data_provider,
            "provider_symbol": self.provider_symbol,
            "futures_symbol": self.futures_symbol,
            "micro_futures_symbol": self.micro_futures_symbol,
            "market_hours": self.market_hours,
            "currency": self.currency,
            "enabled": self.enabled,
            "instrument_status": self.instrument_status,
            "source": self.source,
            "registry_version": self.registry_version,
            "last_verified_at": self.last_verified_at.isoformat(),
        }


@dataclass(frozen=True)
class FTMORegistryRefreshReport:
    observed_at: datetime
    added_symbols: tuple[str, ...]
    removed_symbols: tuple[str, ...]
    status_changes: tuple[str, ...]
    applied: bool = False


class FTMOInstrumentRegistry:
    def __init__(self, instruments: Iterable[FTMOInstrument]) -> None:
        self._instruments = tuple(instruments)
        self._by_symbol: dict[str, FTMOInstrument] = {}
        provider_owners: dict[tuple[str, str], FTMOInstrument] = {}
        for instrument in self._instruments:
            key = instrument.ftmo_symbol.casefold()
            if key in self._by_symbol:
                raise ValueError(f"duplicate FTMO symbol: {instrument.ftmo_symbol}")
            self._by_symbol[key] = instrument
            if instrument.provider_symbol:
                provider_key = (instrument.market_data_provider.casefold(), instrument.provider_symbol.casefold())
                previous = provider_owners.get(provider_key)
                if previous is not None and previous.underlying_market.casefold() != instrument.underlying_market.casefold():
                    raise ValueError(
                        f"duplicate provider mapping {instrument.market_data_provider}:{instrument.provider_symbol} "
                        f"for unrelated markets {previous.ftmo_symbol} and {instrument.ftmo_symbol}"
                    )
                provider_owners[provider_key] = instrument

    def all(self, *, enabled_only: bool = False) -> tuple[FTMOInstrument, ...]:
        return tuple(item for item in self._instruments if item.enabled or not enabled_only)

    def for_asset_class(self, asset_class: FTMOAssetClass, *, enabled_only: bool = True) -> tuple[FTMOInstrument, ...]:
        return tuple(
            item for item in self._instruments
            if item.asset_class is asset_class and (item.enabled or not enabled_only)
        )

    def resolve(self, ftmo_symbol: str) -> FTMOInstrument:
        try:
            return self._by_symbol[ftmo_symbol.strip().casefold()]
        except KeyError as exc:
            raise KeyError(f"unsupported FTMO instrument: {ftmo_symbol}") from exc

    def contains_underlying(self, asset_class: FTMOAssetClass, underlying_symbol: str) -> bool:
        target = underlying_symbol.strip().upper()
        return any(
            item.enabled and item.asset_class is asset_class and item.underlying_symbol.upper() == target
            for item in self._instruments
        )

    def refresh_report(self, *, timeout: float = 15.0) -> FTMORegistryRefreshReport:
        request = Request(FTMO_SYMBOLS_URL, headers={"Accept": "application/json", "User-Agent": "Monatise/1.0"})
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed official FTMO endpoint
            payload = json.loads(response.read().decode("utf-8"))
        rows = payload.get("data", {}).get("symbols", []) if isinstance(payload, dict) else []
        relevant_classes = {"Equities CFD", "Crypto CFD", "Cash CFD", "Metals CFD"}
        live = {
            str(row.get("code") or "").casefold(): bool(row.get("active"))
            for row in rows if isinstance(row, dict) and row.get("assetClass") in relevant_classes and row.get("code")
        }
        known = {item.ftmo_symbol.casefold(): item for item in self._instruments}
        added = tuple(sorted(str(row.get("code")) for row in rows if isinstance(row, dict) and row.get("assetClass") in relevant_classes and str(row.get("code") or "").casefold() not in known))
        removed = tuple(sorted(item.ftmo_symbol for key, item in known.items() if key not in live))
        changes = tuple(sorted(item.ftmo_symbol for key, item in known.items() if key in live and live[key] != (item.instrument_status == "active")))
        return FTMORegistryRefreshReport(datetime.now(timezone.utc), added, removed, changes, applied=False)


def _stock(symbol: str, name: str, underlying: str, exchange: str, currency: str, provider: str, provider_symbol: str | None) -> FTMOInstrument:
    return FTMOInstrument(FTMOAssetClass.STOCK, symbol, name, underlying, name.removesuffix(", Spot CFD"), exchange, provider, provider_symbol, None, None, "FTMO published platform schedule", currency, True, "active", REGISTRY_SOURCE, REGISTRY_VERSION, REGISTRY_VERIFIED_AT)


def _crypto(symbol: str, name: str, underlying: str) -> FTMOInstrument:
    return FTMOInstrument(FTMOAssetClass.CRYPTO, symbol, name, underlying, f"{underlying}/USD crypto spot CFD", "FTMO liquidity providers", "coinglass", underlying, None, None, "FTMO crypto schedule; weekend maintenance varies", "USD", True, "active", REGISTRY_SOURCE, REGISTRY_VERSION, REGISTRY_VERIFIED_AT)


def _future(symbol: str, name: str, underlying: str, venue: str, root: str, micro: str | None, currency: str) -> FTMOInstrument:
    return FTMOInstrument(FTMOAssetClass.FUTURES_LINKED, symbol, name, underlying, underlying, venue, "exchange_futures", root, root, micro, "FTMO published platform schedule; futures venue hours differ", currency, True, "active", REGISTRY_SOURCE, REGISTRY_VERSION, REGISTRY_VERIFIED_AT)


_US_NASDAQ = {"AAPL", "AMZN", "ARM", "ASML", "AVGO", "AZN", "CSCO", "GOOG", "INTC", "META", "MSFT", "MSTR", "NFLX", "NVDA", "PLTR", "QCOM", "SBUX", "TSLA", "ZM"}
_EU_STOCKS = {
    "ADSGn": ("ADS.DE", "XETRA"), "AIRF": ("AIR.PA", "Euronext Paris"), "ALVG": ("ALV.DE", "XETRA"),
    "BAYGn": ("BAYN.DE", "XETRA"), "DBKGn": ("DBK.DE", "XETRA"), "IBE": ("IBE.MC", "BME"),
    "LVMH": ("MC.PA", "Euronext Paris"), "SAN": ("SAN.MC", "BME"), "SIEGn": ("SIE.DE", "XETRA"),
    "VOWG_p": ("VOW3.DE", "XETRA"), "TTE": ("TTE.PA", "Euronext Paris"), "BMW": ("BMW.DE", "XETRA"),
    "MBG": ("MBG.DE", "XETRA"),
}

_STOCK_ROWS = (
    ("AAPL", "Apple, Spot CFD", "USD"), ("ADSGn", "Adidas AG, Spot CFD", "EUR"), ("AIRF", "Air France KLM, Spot CFD", "EUR"),
    ("ALVG", "Allianz, Spot CFD", "EUR"), ("AMZN", "Amazon Com, Spot CFD", "USD"), ("BA", "Boeing Co, Spot CFD", "USD"),
    ("BABA", "Alibaba Group, Spot CFD", "USD"), ("BAC", "Bank of America, Spot CFD", "USD"), ("BAYGn", "Bayer, Spot CFD", "EUR"),
    ("CSCO", "Cisco Systems, Spot CFD", "USD"), ("CVX", "Chevron, Spot CFD", "USD"), ("DBKGn", "Deutsche Bank, Spot CFD", "EUR"),
    ("DIS", "Walt Disney, Spot CFD", "USD"), ("META", "Meta Platforms, Spot CFD", "USD"), ("FDX", "FedEx, Spot CFD", "USD"),
    ("GE", "General Aerospace, Spot CFD", "USD"), ("GM", "General Motors, Spot CFD", "USD"), ("GOOG", "Alphabet Class C, Spot CFD", "USD"),
    ("IBE", "Iberdrola, Spot CFD", "EUR"), ("IBM", "IBM Corp, Spot CFD", "USD"), ("INTC", "Intel Corp, Spot CFD", "USD"),
    ("JNJ", "Johnson and Johnson, Spot CFD", "USD"), ("JPM", "JPMorgan Chase, Spot CFD", "USD"), ("KO", "Coca-Cola, Spot CFD", "USD"),
    ("LVMH", "LVMH, Spot CFD", "EUR"), ("MCD", "McDonald's, Spot CFD", "USD"), ("MSFT", "Microsoft, Spot CFD", "USD"),
    ("NFLX", "Netflix, Spot CFD", "USD"), ("NVDA", "NVIDIA, Spot CFD", "USD"), ("PFE", "Pfizer, Spot CFD", "USD"),
    ("QCOM", "Qualcomm, Spot CFD", "USD"), ("RACE", "Ferrari, Spot CFD", "USD"), ("SAN", "Banco Santander, Spot CFD", "EUR"),
    ("SIEGn", "Siemens AG, Spot CFD", "EUR"), ("T", "AT&T, Spot CFD", "USD"), ("TSLA", "Tesla, Spot CFD", "USD"),
    ("V", "Visa, Spot CFD", "USD"), ("VOWG_p", "Volkswagen, Spot CFD", "EUR"), ("WMT", "Walmart, Spot CFD", "USD"),
    ("XOM", "Exxon Mobil, Spot CFD", "USD"), ("ZM", "Zoom Video Communications, Spot CFD", "USD"),
    ("RTX", "Raytheon Technologies, Spot CFD", "USD"), ("LMT", "Lockheed Martin, Spot CFD", "USD"),
    ("PLTR", "Palantir Technologies, Spot CFD", "USD"), ("AMD", "Advanced Micro Devices, Spot CFD", "USD"),
    ("AVGO", "Broadcom, Spot CFD", "USD"), ("SBUX", "Starbucks, Spot CFD", "USD"), ("MSTR", "MicroStrategy, Spot CFD", "USD"),
    ("GME", "GameStop, Spot CFD", "USD"), ("NKE", "Nike, Spot CFD", "USD"), ("ARM", "Arm Holdings Inc, Spot CFD", "USD"),
    ("SNOW", "Snowflake Inc, Spot CFD", "USD"), ("ASML", "ASML Holding, Spot CFD", "USD"), ("AZN", "AstraZeneca PLC, Spot CFD", "USD"),
    ("BRK.B", "Berkshire Hathaway Inc Class B, Spot CFD", "USD"), ("TTE", "TotalEnergies, Spot CFD", "EUR"),
    ("BMW", "BMW AG, Spot CFD", "EUR"), ("MBG", "Mercedes-Benz Group AG, Spot CFD", "EUR"), ("SPCX", "SpaceX, Spot CFD", "USD"),
)

_CRYPTO_ROWS = (
    ("BTCUSD", "Bitcoin vs US Dollar, Spot CFD", "BTC"), ("DASHUSD", "Dash vs US Dollar, Spot CFD", "DASH"),
    ("ETHUSD", "Ethereum vs US Dollar, Spot CFD", "ETH"), ("LTCUSD", "Litecoin vs US Dollar, Spot CFD", "LTC"),
    ("XRPUSD", "Ripple vs US Dollar, Spot CFD", "XRP"), ("XMRUSD", "Monero vs US Dollar, Spot CFD", "XMR"),
    ("NEOUSD", "Neo vs US Dollar, Spot CFD", "NEO"), ("ADAUSD", "Cardano vs US Dollar, Spot CFD", "ADA"),
    ("DOTUSD", "Polkadot vs US Dollar, Spot CFD", "DOT"), ("DOGEUSD", "Dogecoin vs US Dollar, Spot CFD", "DOGE"),
    ("SOLUSD", "Solana vs US Dollar, Spot CFD", "SOL"), ("AVAUSD", "Avalanche vs US Dollar, Spot CFD", "AVAX"),
    ("BCHUSD", "Bitcoin Cash vs US Dollar, Spot CFD", "BCH"), ("ETCUSD", "Ethereum Classic vs US Dollar, Spot CFD", "ETC"),
    ("BNBUSD", "Binance Coin vs US Dollar, Spot CFD", "BNB"), ("SANUSD", "The Sandbox vs US Dollar, Spot CFD", "SAND"),
    ("LNKUSD", "Chainlink vs US Dollar, Spot CFD", "LINK"), ("NERUSD", "NEAR Protocol vs US Dollar, Spot CFD", "NEAR"),
    ("ALGUSD", "Algorand vs US Dollar, Spot CFD", "ALGO"), ("ICPUSD", "Internet Computer vs US Dollar, Spot CFD", "ICP"),
    ("AAVUSD", "AAVE vs US Dollar, Spot CFD", "AAVE"), ("BARUSD", "Hedera vs US Dollar, Spot CFD", "HBAR"),
    ("GALUSD", "GALA vs US Dollar, Spot CFD", "GALA"), ("GRTUSD", "The Graph vs US Dollar, Spot CFD", "GRT"),
    ("IMXUSD", "Immutable X vs US Dollar, Spot CFD", "IMX"), ("MANUSD", "Decentraland vs US Dollar, Spot CFD", "MANA"),
    ("VECUSD", "VeChain vs US Dollar, Spot CFD", "VET"), ("XLMUSD", "Stellar Lumens vs US Dollar, Spot CFD", "XLM"),
    ("UNIUSD", "Uniswap vs US Dollar, Spot CFD", "UNI"), ("XTZUSD", "Tezos vs US Dollar, Spot CFD", "XTZ"),
)

_FUTURES_ROWS = (
    ("XAG/USD", "Silver vs US Dollar, Spot CFD", "Silver", "COMEX", "SI", "SIL", "USD"),
    ("XAG/EUR", "Silver vs Euro, Spot CFD", "Silver", "COMEX", "SI", "SIL", "EUR"),
    ("XAG/AUD", "Silver vs Australian Dollar, Spot CFD", "Silver", "COMEX", "SI", "SIL", "AUD"),
    ("XAU/USD", "Gold vs US Dollar, Spot CFD", "Gold", "COMEX", "GC", "MGC", "USD"),
    ("XAU/EUR", "Gold vs Euro, Spot CFD", "Gold", "COMEX", "GC", "MGC", "EUR"),
    ("XAU/AUD", "Gold vs Australian Dollar, Spot CFD", "Gold", "COMEX", "GC", "MGC", "AUD"),
    ("XPD/USD", "Palladium vs US Dollar, Spot CFD", "Palladium", "NYMEX", "PA", None, "USD"),
    ("XPT/USD", "Platinum vs US Dollar, Spot CFD", "Platinum", "NYMEX", "PL", None, "USD"),
    ("AUS200.cash", "Australia 200 Index, Spot CFD", "S&P/ASX 200", "ASX", "AP", None, "AUD"),
    ("US30.cash", "Dow Jones Industrial Average Index, Spot CFD", "Dow Jones Industrial Average", "CBOT", "YM", "MYM", "USD"),
    ("SPN35.cash", "Spain 35 Index, Spot CFD", "IBEX 35", "MEFF", "IBEX", "MIB", "EUR"),
    ("EU50.cash", "Euro Stoxx 50 Index, Spot CFD", "EURO STOXX 50", "Eurex", "FESX", "FSXE", "EUR"),
    ("FRA40.cash", "France 40 Index, Spot CFD", "CAC 40", "Euronext", "FCE", "MFC", "EUR"),
    ("GER40.cash", "German 40 Index, Spot CFD", "DAX 40", "Eurex", "FDAX", "FDXS", "EUR"),
    ("HK50.cash", "Hong Kong Index, Spot CFD", "Hang Seng Index", "HKEX", "HSI", "MHI", "HKD"),
    ("JP225.cash", "Japan 225 Index, Spot CFD", "Nikkei 225", "CME", "NKD", "MNK", "JPY"),
    ("N25.cash", "Netherlands 25 Index, Spot CFD", "AEX Index", "Euronext", "FTI", None, "EUR"),
    ("US100.cash", "NASDAQ 100 Index, Spot CFD", "Nasdaq-100", "CME", "NQ", "MNQ", "USD"),
    ("US500.cash", "S&P 500 Index, Spot CFD", "S&P 500", "CME", "ES", "MES", "USD"),
    ("UK100.cash", "FTSE 100 Index, Spot CFD", "FTSE 100", "ICE Futures Europe", "Z", None, "GBP"),
    ("UKOIL.cash", "Crude Oil Brent, Spot CFD", "Brent Crude Oil", "ICE Futures Europe", "B", None, "USD"),
    ("USOIL.cash", "WTI Crude Oil, Spot CFD", "WTI Crude Oil", "NYMEX", "CL", "MCL", "USD"),
    ("NATGAS.cash", "Natural Gas, Spot CFD", "Henry Hub Natural Gas", "NYMEX", "NG", "MNG", "USD"),
    ("DXY.cash", "Dollar Index, Spot CFD", "U.S. Dollar Index", "ICE Futures U.S.", "DX", None, "USD"),
    ("US2000.cash", "Russell 2000 Index, Spot CFD", "Russell 2000", "CME", "RTY", "M2K", "USD"),
    ("COCOA.c", "Cocoa vs US Dollar, Spot CFD", "Cocoa", "ICE Futures U.S.", "CC", None, "USD"),
    ("COFFEE.c", "Coffee vs US Dollar, Spot CFD", "Coffee C", "ICE Futures U.S.", "KC", None, "USD"),
    ("CORN.c", "Corn vs US Dollar, Spot CFD", "Corn", "CBOT", "ZC", "XC", "USD"),
    ("SOYBEAN.c", "Soybean vs US Dollar, Spot CFD", "Soybeans", "CBOT", "ZS", "XK", "USD"),
    ("WHEAT.c", "Wheat, Spot CFD", "Chicago SRW Wheat", "CBOT", "ZW", "XW", "USD"),
    ("XCU/USD", "Copper vs US Dollar, Spot CFD", "High Grade Copper", "COMEX", "HG", "MHG", "USD"),
    ("HEATOIL.c", "Heating Oil, Spot CFD", "NY Harbor ULSD", "NYMEX", "HO", None, "USD"),
    ("COTTON.c", "Cotton vs US Dollar, Spot CFD", "Cotton No. 2", "ICE Futures U.S.", "CT", None, "USD"),
    ("SUGAR.c", "Sugar vs US Dollar, Spot CFD", "Sugar No. 11", "ICE Futures U.S.", "SB", None, "USD"),
)


def _builtins() -> tuple[FTMOInstrument, ...]:
    stocks: list[FTMOInstrument] = []
    for symbol, name, currency in _STOCK_ROWS:
        if symbol in _EU_STOCKS:
            provider_symbol, exchange = _EU_STOCKS[symbol]
            stocks.append(_stock(symbol, name, provider_symbol, exchange, currency, "yahoo_finance", provider_symbol))
        elif symbol == "SPCX":
            stocks.append(_stock(symbol, name, symbol, "Private market / FTMO CFD", currency, "unavailable", None))
        else:
            exchange = "NASDAQ" if symbol in _US_NASDAQ else "NYSE"
            stocks.append(_stock(symbol, name, symbol, exchange, currency, "alpaca", symbol))
    crypto = [_crypto(*row) for row in _CRYPTO_ROWS]
    futures = [_future(*row) for row in _FUTURES_ROWS]
    return tuple((*stocks, *futures, *crypto))


FTMO_REGISTRY = FTMOInstrumentRegistry(_builtins())

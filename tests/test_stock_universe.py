import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from monatise.application.deployment import (
    OrchestrationRuntime,
    _interleave_stock_candidates,
    _setup_alert_state,
    _setup_materially_changed,
)
from monatise.application.stock_universe import (
    StockCandidate,
    StockUniverseConfiguration,
    build_technical_stock_setup,
    eligible_stock_assets,
    rank_stock_universe,
)
from monatise.application.workflows import TelegramNotifier


NOW = datetime(2026, 8, 19, 15, tzinfo=timezone.utc)
CONFIG = StockUniverseConfiguration(shortlist_per_side=2)


def asset(symbol="AAA", name="Alpha Corp", **overrides):
    value = {"symbol": symbol, "name": name, "status": "active", "tradable": True, "exchange": "NASDAQ"}
    value.update(overrides)
    return value


def snapshot(price=100, previous=98, volume=200_000, bid=99.95, ask=100.05):
    return {"dailyBar": {"c": price, "h": price + 1, "l": price - 2, "v": volume}, "prevDailyBar": {"c": previous}, "latestQuote": {"bp": bid, "ap": ask}}


def bars(side="long", count=60):
    rows = []
    start = NOW - timedelta(hours=count)
    for index in range(count):
        close = 100 + index * 0.2 if side == "long" else 120 - index * 0.2
        rows.append({"h": close + 0.4, "l": close - 0.4, "c": close, "v": 1000, "t": (start + timedelta(hours=index)).isoformat()})
    if side == "long":
        rows[-1].update({"h": 115, "l": 113.5, "c": 114.8, "v": 3000})
    else:
        rows[-1].update({"h": 107, "l": 105, "c": 105.2, "v": 3000})
    return rows


def test_universe_filters_inactive_otc_and_leveraged_assets():
    eligible, excluded = eligible_stock_assets([
        asset("AAA"), asset("OLD", status="inactive"), asset("OTC", exchange="OTC"), asset("LEV", name="Ultra 3X Bull ETF"),
    ], CONFIG)
    assert [row["symbol"] for row in eligible] == ["AAA"]
    assert excluded == {"inactive_or_untradable": 1, "unsupported_exchange": 1, "leveraged_or_inverse": 1}


def test_unlimited_universe_does_not_drop_assets_late_in_provider_order():
    assets = [asset(f"S{index}") for index in range(6_005)]
    eligible, excluded = eligible_stock_assets(assets, StockUniverseConfiguration(maximum_universe_size=0))
    assert len(eligible) == 6_005
    assert eligible[-1]["symbol"] == "S6004"
    assert excluded == {}


def test_stage_a_ranks_long_and_short_separately_and_filters_quality():
    assets = [asset("LONG"), asset("SHORT"), asset("CHEAP"), asset("WIDE")]
    snapshots = {
        "LONG": snapshot(105, 100), "SHORT": snapshot(95, 100),
        "CHEAP": snapshot(2, 2.1), "WIDE": snapshot(100, 99, bid=95, ask=105),
    }
    longs, shorts, exclusions = rank_stock_universe(assets, snapshots, CONFIG)
    assert [item.symbol for item in longs] == ["LONG"]
    assert [item.symbol for item in shorts] == ["SHORT"]
    assert exclusions == {"price_below_minimum": 1, "spread_too_wide": 1}


def test_deep_analysis_builds_confirmed_long_and_short_setups():
    long = StockCandidate("LONG", "Long Corp", "long", 5, 100, 10, 50_000_000, ())
    short = StockCandidate("SHORT", "Short Corp", "short", 5, 100, 10, 50_000_000, ())
    long_result = build_technical_stock_setup(long, bars("long"), bars("long"), configuration=CONFIG, now=NOW)
    short_result = build_technical_stock_setup(short, bars("short"), bars("short"), configuration=CONFIG, now=NOW)
    assert long_result["setup_status"] == "confirmed" and long_result["score"] >= 7
    assert short_result["setup_status"] == "confirmed" and short_result["score"] <= -7
    assert long_result["stop_loss"] < long_result["entry"] < long_result["target"]
    assert short_result["target"] < short_result["entry"] < short_result["stop_loss"]


def test_quiver_and_flashalpha_can_veto_but_not_create_technical_setup():
    candidate = StockCandidate("LONG", "Long Corp", "long", 5, 100, 10, 50_000_000, ())
    result = build_technical_stock_setup(
        candidate, bars("long"), bars("long"), configuration=CONFIG, now=NOW,
        quiver={"summary": {"score": -3}}, flashalpha={"underlying_price": 90, "gamma_flip": 100},
    )
    assert result["decision"] == "NO_TRADE"
    assert "quiver_material_conflict" in result["suppression_reasons"]
    assert "flashalpha_positioning_conflict" in result["suppression_reasons"]


def test_imminent_earnings_suppresses_otherwise_confirmed_setup():
    candidate = StockCandidate("LONG", "Long Corp", "long", 5, 100, 10, 50_000_000, ())
    result = build_technical_stock_setup(
        candidate, bars("long"), bars("long"), configuration=CONFIG, now=NOW,
        finnhub={"earnings": [{"date": (NOW + timedelta(days=1)).date().isoformat()}]},
    )
    assert result["decision"] == "NO_TRADE"
    assert "imminent_earnings" in result["suppression_reasons"]


def test_market_stock_telegram_contains_required_provenance_and_risk_fields():
    candidate = StockCandidate("LONG", "Long Corp", "long", 5, 100, 10, 50_000_000, ())
    result = build_technical_stock_setup(candidate, bars("long"), bars("long"), configuration=CONFIG, now=NOW)
    message = TelegramNotifier.format_market_stock_setup(result)
    assert "Long Corp" in message and "Direction: LONG" in message
    assert "Entry:" in message and "Invalidation:" in message and "Targets:" in message
    assert "Quiver:" in message and "no trade was executed" in message


def test_shortlist_interleaving_balances_provider_enrichment_slots():
    longs = [StockCandidate(f"L{index}", "Long", "long", 5, 100, 10, 50_000_000, ()) for index in range(5)]
    shorts = [StockCandidate(f"S{index}", "Short", "short", 5, 100, 10, 50_000_000, ()) for index in range(5)]
    ordered = _interleave_stock_candidates(longs, shorts)
    assert [candidate.side for candidate in ordered[:6]] == ["long", "short", "long", "short", "long", "short"]
    assert [candidate.side for candidate in ordered[:4]] == ["long", "short", "long", "short"]


def test_setup_dedupe_ignores_noise_but_accepts_material_changes():
    previous = _setup_alert_state({"direction": "LONG", "score": 8, "entry": 100, "stop_loss": 98, "targets": [104]})
    noisy = _setup_alert_state({"direction": "LONG", "score": 8, "entry": 100.1, "stop_loss": 98.1, "targets": [104.1]})
    moved = _setup_alert_state({"direction": "LONG", "score": 8, "entry": 100.6, "stop_loss": 98.6, "targets": [104.7]})
    reversed_setup = _setup_alert_state({"direction": "SHORT", "score": -8, "entry": 100, "stop_loss": 102, "targets": [96]})
    encoded = json.dumps(previous).encode()
    assert not _setup_materially_changed(encoded, noisy)
    assert _setup_materially_changed(encoded, moved)
    assert _setup_materially_changed(encoded, reversed_setup)


class Redis:
    def __init__(self): self.values = {}
    async def get(self, key): return self.values.get(key)
    async def set(self, key, value, **kwargs):
        if kwargs.get("nx") and key in self.values: return False
        self.values[key] = value
        return True
    async def delete(self, key): self.values.pop(key, None)


def test_runtime_scans_dynamic_universe_publishes_only_qualified_and_dedupes(monkeypatch):
    class Alpaca:
        def active_stock_assets(self): return [asset("LONG"), asset("SHORT")]
        def stock_snapshots(self, symbols): return {"LONG": snapshot(105, 100), "SHORT": snapshot(95, 100)}
    class Telegram:
        def __init__(self): self.messages = []
        async def stock_analysis_notification(self, message): self.messages.append(message)
    monkeypatch.setattr("monatise.application.deployment.AlpacaMarketDataAdapter.from_env", classmethod(lambda cls: Alpaca()))
    class Registry:
        def for_asset_class(self, _asset_class):
            return tuple(SimpleNamespace(
                ftmo_symbol=symbol, underlying_symbol=symbol, provider_symbol=symbol,
                display_name=f"{symbol} Corp, Spot CFD", exchange="NASDAQ",
                market_data_provider="alpaca", registry_version="test-v1",
            ) for symbol in ("LONG", "SHORT"))
    monkeypatch.setattr("monatise.application.deployment.FTMO_REGISTRY", Registry())
    runtime = OrchestrationRuntime.__new__(OrchestrationRuntime)
    runtime.redis, runtime.telegram = Redis(), Telegram()
    async def analyze(candidate, configuration, index):
        return {"asset": candidate.symbol, "company_name": candidate.name, "direction": candidate.side.upper(), "decision": "BUY_WATCH", "score": 8, "score_threshold": 7, "setup_status": "confirmed", "current_price": 100, "entry": 100, "stop_loss": 98, "target": 104, "targets": [104], "reward_risk": 2, "additional_context": {}, "execution": {"enabled": False}}
    runtime._analyze_market_stock = analyze
    first = asyncio.run(runtime._run_stock_universe_scan(CONFIG, 3600, "test"))
    second = asyncio.run(runtime._run_stock_universe_scan(CONFIG, 3600, "test"))
    assert first["universe_source"] == "ftmo_registry"
    assert first["universe_size"] == 2 and first["deep_analysis_attempted"] == 2
    assert first["telegram_published"] == 2
    assert second["telegram_published"] == 0 and second["suppressions"]["duplicate_unchanged"] == 2

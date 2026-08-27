from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from monatise.application.ftmo_registry import FTMOAssetClass, FTMO_REGISTRY
from monatise.application.production import ProductionASGI
from monatise.application.telegram_analysis import (
    TelegramAnalysisError,
    format_analysis,
    normalize_analysis,
    recommended_risk_percent,
    request_identity,
    resolve_telegram_instrument,
    signal_identity,
)


NOW = datetime(2026, 8, 27, 14, 0, tzinfo=timezone.utc)


class Repository:
    def __init__(self):
        self.requests, self.analyses = {}, {}
        self.bridge_value = {
            "quotes": {
                "XAUUSD": {"trade_mode": "full"},
                "BTCUSD": {"trade_mode": "full"},
                "ETHUSD": {"trade_mode": "full"},
                "US100.cash": {"trade_mode": "full"},
                "AAPL": {"trade_mode": "full"},
            }
        }

    async def claim_telegram_analysis_request(self, request):
        if request["request_id"] in self.requests:
            return False
        self.requests[request["request_id"]] = dict(request)
        return True

    async def telegram_analysis_request(self, request_id):
        value = self.requests.get(request_id)
        return (dict(value), 1) if value else None

    async def finish_telegram_analysis_request(self, request_id, changes):
        self.requests[request_id].update(changes)
        return dict(self.requests[request_id])

    async def save_telegram_analysis(self, analysis):
        if analysis["analysis_id"] in self.analyses:
            return False
        self.analyses[analysis["analysis_id"]] = dict(analysis)
        return True

    async def bridge(self):
        return self.bridge_value

    async def attach_proposal_telegram_message(self, proposal_id, message_id):
        self.proposal_telegram_message = (proposal_id, message_id)
        return {"proposal_id": proposal_id, "telegram_message_id": message_id}


class Master:
    def __init__(self):
        self.repository = Repository()
        self.proposals = []

    def authorized(self, user_id, chat_type):
        return user_id == "42" and chat_type == "private"

    async def execution_symbol_for(self, instrument, **_kwargs):
        candidates = {
            "XAU/USD": "XAUUSD", "BTCUSD": "BTCUSD", "ETHUSD": "ETHUSD",
            "US100.cash": "US100.cash", "AAPL": "AAPL", "EUR/USD": "EURUSD",
        }
        return candidates[instrument.ftmo_symbol]

    async def create_signal_proposal(self, **kwargs):
        self.proposals.append(kwargs)
        proposal_id = "a1b2c3d4e5f6"
        return {
            "proposal_id": proposal_id,
            "kind": "open_trade",
            "signal_id": kwargs["signal_id"],
            "analysis_id": kwargs["analysis_id"],
            "telegram_request_id": kwargs["telegram_request_id"],
            "symbol": kwargs["symbol"],
            "side": "buy" if kwargs["direction"].casefold() == "long" else "sell",
            "order_type": "market",
            "strategy": kwargs["strategy"],
            "market_session": "NEW_YORK",
            "session_checked_at": NOW.isoformat(),
            "market_open": True,
            "broker_break_proximity": "SAFE",
            "analysis_price": str(kwargs["analysis_entry"]),
            "entry": "2500.2",
            "stop_loss": "2490",
            "take_profit": "2520",
            "recommended_risk_fraction": str(float(kwargs["recommended_risk_percent"]) / 100),
            "risk_fraction": "0.0124",
            "risk_amount": "124",
            "volume": "0.10",
            "quote_bid": "2500.0",
            "quote_ask": "2500.2",
            "expires_at": kwargs["signal_expires_at"].isoformat(),
            "conviction": kwargs["conviction"],
        }


class Telegram:
    def __init__(self):
        self.messages, self.proposals = [], []

    async def command_response(self, message):
        self.messages.append(message)
        return 100 + len(self.messages)

    async def trade_proposal(self, message, proposal_id):
        self.proposals.append((proposal_id, message))
        return 200 + len(self.proposals)


def qualified_crypto(symbol="BTC"):
    return {
        "symbol": symbol,
        "classification": "trend",
        "direction": "long",
        "entry_confirmation_status": "confirmed",
        "entry": 65000,
        "invalidation": 64000,
        "target": 67000,
        "targets": [67000, 68000],
        "interval": "15m",
        "score": 8,
        "score_threshold": 7,
        "conviction": 0.8,
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
        "current_reference_price": 65000,
        "market_state": "trend_up",
        "derivatives": {"open_interest": 10_000_000, "funding_rate": 0.0001, "cvd_delta": 250_000},
        "market_structure": {"state": "bullish_continuation", "latest_break": "bullish_bos"},
        "liquidity": {"sweep": "confirmed"},
        "audit_reference": "run-1",
    }


class Runtime:
    def __init__(self, crypto=None):
        self.environment = {"MONATISE_TELEGRAM_CHAT_ID": "42"}
        self.ftmo_registry = FTMO_REGISTRY
        self.ftmo_master = Master()
        self.telegram = Telegram()
        self.crypto = crypto or qualified_crypto()
        self.calls = []

    async def analyse(self, symbol, **kwargs):
        self.calls.append(("crypto", symbol, kwargs))
        return dict(self.crypto)

    async def analyse_stock(self, symbol, **_kwargs):
        self.calls.append(("stock", symbol, {}))
        return {
            "asset": symbol, "decision": "BUY_WATCH", "direction": "LONG",
            "setup_status": "confirmed", "entry": 200, "stop_loss": 195, "target": 210,
            "score": 8, "score_threshold": 7, "current_price": 200,
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
            "analysis_provider": "alpaca+quiver", "analysis_instrument": symbol,
            "analysis_sources": [
                {"provider": "alpaca", "status": "used", "role": "required_market_data"},
                {"provider": "quiver", "status": "used", "role": "directional_intelligence"},
                {"provider": "ftmo_mt5", "status": "not_requested", "role": "execution_pricing"},
            ],
            "provider_consensus": "PARTIAL", "fallback_status": "not_available_no_verified_fallback",
        }

    async def analyse_ftmo_futures_instrument(self, instrument):
        self.calls.append(("futures", instrument.futures_symbol, {}))
        return {
            "decision": "BUY_WATCH", "direction": "LONG", "setup_status": "confirmed",
            "entry": 3500, "stop_loss": 3485, "target": 3530, "score": 8,
            "score_threshold": 7, "current_price": 3500, "timeframe": "intraday",
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
            "data_source": "FlashAlpha",
        }


def run_request(runtime, text, *, update_id=1, user_id="42", chat_type="private"):
    app = ProductionASGI(runtime)
    app._telegram_command_context = {
        "update_id": update_id, "user_id": user_id, "chat_type": chat_type, "callback_query_id": "",
    }
    asyncio.run(app._handle_telegram_command(text))
    return app


@pytest.mark.parametrize("alias,canonical", [
    ("gold", "XAU/USD"), ("XAU", "XAU/USD"), ("XAUUSD", "XAU/USD"),
    ("btc", "BTCUSD"), ("bitcoin", "BTCUSD"), ("BTCUSDT", "BTCUSD"),
    ("eth", "ETHUSD"), ("nasdaq", "US100.cash"), ("nq", "US100.cash"),
    ("us100", "US100.cash"), ("US100.cash", "US100.cash"), ("AAPL", "AAPL"),
    ("EURUSD", "EUR/USD"), ("USDJPY", "USD/JPY"),
])
def test_supported_aliases_resolve_without_guessing(alias, canonical):
    assert resolve_telegram_instrument(alias, FTMO_REGISTRY).canonical == canonical


def test_unsupported_symbol_fails_closed():
    with pytest.raises(TelegramAnalysisError, match="mapping"):
        resolve_telegram_instrument("PEPE", FTMO_REGISTRY)


@pytest.mark.parametrize("score,expected", [(7, "1.00"), (8, "1.25"), (9, "1.50"), (10, "2.00"), (0, "0.50")])
def test_recommended_risk_is_conviction_scaled_below_ceiling(score, expected):
    assert str(recommended_risk_percent(score)) == expected
    assert recommended_risk_percent(score) < 3


def test_request_and_signal_identities_are_deterministic_and_immutable():
    first = request_identity("42", 10)
    second = request_identity("42", 10)
    assert first == second
    setup = {"canonical_instrument": "BTCUSD", "direction": "LONG", "entry": 1, "stop_loss": .9, "targets": [1.2], "expires_at": "x"}
    assert signal_identity(*first, setup) == signal_identity(*second, setup)
    assert signal_identity(*first, setup) != signal_identity(*first, {**setup, "targets": [1.3]})


def test_analyze_btc_is_disabled_for_ftmo_telegram():
    runtime = Runtime()
    run_request(runtime, "/analyze BTC", update_id=20)
    assert runtime.calls == []
    assert runtime.ftmo_master.proposals == []
    assert "Crypto is disabled" in runtime.telegram.messages[-1]


def test_analyze_forex_is_rejected_without_calling_a_provider():
    runtime = Runtime()
    run_request(runtime, "/analyze EURUSD", update_id=120)
    assert runtime.calls == []
    assert runtime.ftmo_master.proposals == []
    assert "Forex analysis is out of scope" in runtime.telegram.messages[-1]


def test_gold_alias_runs_fresh_futures_provider_path():
    runtime = Runtime()
    run_request(runtime, "/gold", update_id=21)
    assert runtime.calls[0][0:2] == ("futures", "GC")
    assert runtime.ftmo_master.proposals[0]["symbol"] == "XAUUSD"


def test_analysis_alias_runs_stock_provider_path():
    runtime = Runtime()
    run_request(runtime, "/analysis AAPL", update_id=22)
    assert runtime.calls[0][0:2] == ("stock", "AAPL")
    assert runtime.ftmo_master.proposals[0]["symbol"] == "AAPL"


def test_no_trade_returns_full_analysis_without_approval_action():
    runtime = Runtime()
    async def no_trade(symbol, **_kwargs):
        return {"asset": symbol, "decision": "NO_TRADE", "direction": "NONE", "setup_status": "suppressed", "score": 4, "score_threshold": 7, "reasons": ["Stock structure is inconclusive"], "analysis_provider": "alpaca+quiver", "analysis_instrument": symbol}
    runtime.analyse_stock = no_trade
    run_request(runtime, "/analyze AAPL", update_id=23)
    assert runtime.ftmo_master.proposals == []
    assert runtime.telegram.proposals == []
    assert "Decision: NO_TRADE" in runtime.telegram.messages[-1]
    assert "Stock structure is inconclusive" in runtime.telegram.messages[-1]
    request = next(iter(runtime.ftmo_master.repository.requests.values()))
    assert request["proposal_state"] == "NO_TRADE"
    assert request["proposal_id"] is None
    assert request["telegram_message_id"] == 102


def test_waiting_for_entry_zone_does_not_create_market_proposal():
    runtime = Runtime()
    async def waiting(symbol, **_kwargs):
        return {"asset": symbol, "decision": "BUY_WATCH", "direction": "LONG", "setup_status": "confirmed", "entry": None, "entry_zone": {"low": 198, "high": 199}, "current_price": 200, "stop_loss": 195, "target": 205, "targets": [205], "score": 8, "score_threshold": 7, "expires_at": (datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat()}
    runtime.analyse_stock = waiting
    run_request(runtime, "/analyze AAPL", update_id=24)
    assert runtime.ftmo_master.proposals == []
    assert "WAITING FOR ENTRY ZONE" in runtime.telegram.messages[-1]
    request = next(iter(runtime.ftmo_master.repository.requests.values()))
    assert request["proposal_state"] == "CONTEXT_ONLY"
    assert request["proposal_id"] is None


def test_unknown_user_cannot_start_analysis():
    runtime = Runtime()
    run_request(runtime, "/analyze EURUSD", update_id=25, user_id="99")
    assert runtime.calls == []
    assert "not authorized" in runtime.telegram.messages[-1]


def test_duplicate_worker_retry_reuses_completed_response_without_new_analysis_or_order():
    runtime = Runtime()
    app = run_request(runtime, "/analyze AAPL", update_id=26)
    asyncio.run(app._handle_telegram_command("/analyze AAPL"))
    assert len(runtime.calls) == 1
    assert len(runtime.ftmo_master.proposals) == 1


def test_provider_failure_is_deterministic_and_never_creates_proposal():
    runtime = Runtime()

    async def fail(*_args, **_kwargs):
        raise RuntimeError("provider secret detail")

    runtime.analyse_stock = fail
    run_request(runtime, "/analyze AAPL", update_id=27)
    assert runtime.ftmo_master.proposals == []
    assert "ANALYSIS FAILED" in runtime.telegram.messages[-1]
    assert "secret detail" not in runtime.telegram.messages[-1]


def test_analysis_records_session_provenance_and_autonomy_off():
    runtime = Runtime()
    run_request(runtime, "/analyze AAPL", update_id=28)
    analysis = next(iter(runtime.ftmo_master.repository.analyses.values()))
    assert analysis["market_data_provenance"]["provider"] == "alpaca+quiver"
    assert analysis["session"]["session_source"]
    assert analysis["autonomous_execution"] is False


def test_format_no_trade_never_renders_approval_command():
    resolved = resolve_telegram_instrument("BTC", FTMO_REGISTRY)
    raw = qualified_crypto()
    raw.update({"classification": "no_trade", "direction": "none", "entry_confirmation_status": "pending"})
    session = {"analysis_timestamp_utc": NOW.isoformat(), "market_session": "NEW_YORK", "market_open": True, "broker_break_proximity": "SAFE"}
    analysis = normalize_analysis(raw, resolved, request_id="r", analysis_id="a", requested_at=NOW, started_at=NOW, completed_at=NOW, session=session)
    message = format_analysis(analysis)
    assert "No trade proposal created" in message
    assert "/approve" not in message.casefold()


def test_crypto_analysis_and_ftmo_execution_symbols_remain_separate():
    resolved = resolve_telegram_instrument("BTCUSDT", FTMO_REGISTRY)
    assert resolved.analysis_provider == "coinglass"
    assert resolved.analysis_instrument == "BTCUSDT"
    assert resolved.execution_registry_symbol == "BTCUSD"
    assert resolved.asset_class is FTMOAssetClass.CRYPTO

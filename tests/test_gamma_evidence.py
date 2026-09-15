import asyncio
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest

from monatise.application.gamma_evidence import (
    GammaEvidenceLadder,
    validate_certificate,
)
from monatise.application.gamma_reconstruction import (
    CONVENTION,
    MODEL,
    GammaQualityError,
    bs_gamma,
    reconstruct,
)
from monatise.application.market_intelligence import (
    validate_flashalpha_context,
    _validate_flashalpha_context,
    StockMarketIntelligenceCoordinator,
)
from monatise.application.flashalpha_analysis import flashalpha_directional_bias
from monatise.application.ftmo_scanner import publication_allowed
from monatise.application.scan_audit import analysis_trace
from tests.test_market_intelligence import Alpaca, Quiver, Finnhub, NOW
from tests.stock_session_fixtures import calendar_rows


def primary_context(
    status="sensitive_root", *, at=NOW - timedelta(seconds=5), flip=106
):
    return {
        "symbol": "SNOW",
        "source": "FlashAlpha",
        "as_of": at.isoformat(),
        "underlying_price": 108,
        "gamma_flip": flip,
        "gamma_flip_status": status,
        "call_wall": 115,
        "put_wall": 95,
        "net_gex": 1,
        "provider_evidence": {
            name: {
                "symbol": "SNOW",
                "as_of": at.isoformat(),
                "gamma_flip_status": status,
                "gamma_flip": flip,
                "data_as_of": {
                    "equity_feed": at.isoformat(),
                    "equity_options_feed": at.isoformat(),
                },
            }
            for name in ("gex", "levels")
        },
    }


class Primary:
    telemetry = {}

    def __init__(self, value=None):
        self.calls = 0
        self.value = value or primary_context()

    def context(self, symbol):
        self.calls += 1
        return deepcopy(self.value)


def resolve(ladder, context, primary=None):
    def check(value, at):
        return validate_flashalpha_context(
            value, provider_symbol="SNOW", now=at, maximum_age=timedelta(hours=1)
        )

    try:
        check(context, NOW)
        error = None
    except ValueError:
        error = "provider_incomplete"
    return asyncio.run(
        ladder.resolve(
            context=context,
            primary_error=error,
            primary=primary or Primary(),
            symbol="SNOW",
            now=lambda: NOW,
            maximum_age=timedelta(hours=1),
            validate_primary=check,
            validate_supporting=lambda value, at: _validate_flashalpha_context(
                value,
                provider_symbol="SNOW",
                now=at,
                maximum_age=timedelta(hours=1),
                require_gamma=False,
            ),
        )
    )


def cross_estimate(**changes):
    return {
        "symbol": "SNOW",
        "provider": "independent_test_feed",
        "gamma_flip": 106.02,
        "underlying_price": 108,
        "status": "available",
        "as_of": NOW.isoformat(),
        "underlying_as_of": NOW.isoformat(),
        "options_as_of": NOW.isoformat(),
        "methodology": "reprice_book_v1",
        "calculation_owner": "independent_test_feed",
        "data_lineage": ["opra"],
        "scope": "full_chain",
        "sign_convention": CONVENTION,
        "snapshot_id": "book-123",
        "quality": {
            "oi_coverage": 1.0,
            "unique_stable_root": True,
            "maximum_stress_move_fraction": 0.0001,
        },
        **changes,
    }


def cross_provider(value=None):
    return SimpleNamespace(
        name="independent_test_feed",
        gamma_estimate=lambda symbol: deepcopy(value or cross_estimate()),
    )


def test_primary_certified_unchanged_and_no_retry():
    provider = Primary()
    proof, value, error = resolve(
        GammaEvidenceLadder(), primary_context("available"), provider
    )
    assert (
        proof["state"] == "CERTIFIED_PRIMARY" and error is None and provider.calls == 0
    )
    assert proof["gamma_flip"] == 106
    validate_certificate(proof, symbol="SNOW", now=NOW)
    assert (
        flashalpha_directional_bias({**value, "gamma_evidence": proof}, now=NOW)
        == "bullish"
    )


def test_only_new_complete_primary_requery_can_clear_gamma():
    provider = Primary(primary_context("available", at=NOW - timedelta(seconds=1)))
    proof, value, error = resolve(GammaEvidenceLadder(), primary_context(), provider)
    assert (
        provider.calls == 1 and proof["state"] == "CERTIFIED_PRIMARY" and error is None
    )
    assert proof["quarantined_primary"] == {
        "value": 106.0,
        "quality": "sensitive_root",
        "trusted": False,
    }
    assert value["as_of"] != primary_context()["as_of"]


def test_status_change_on_same_snapshot_is_not_a_certified_requery():
    provider = Primary(primary_context("available"))
    proof, _, _ = resolve(GammaEvidenceLadder(), primary_context(), provider)
    assert (
        provider.calls == 1
        and proof["state"] == "UNCERTIFIED"
        and proof["gamma_flip"] is None
    )


@pytest.mark.parametrize(
    "status", ["sensitive_root", "no_boundary", "stored_sign_mismatch", "unknown"]
)
def test_uncertified_candidate_is_never_promoted_without_evidence(status):
    value = primary_context(status)
    original = deepcopy(value)
    proof, _, _ = resolve(GammaEvidenceLadder(), value)
    assert proof["state"] == "UNCERTIFIED" and proof["gamma_flip"] is None
    assert value == original
    assert flashalpha_directional_bias(value, now=NOW) == "neutral"


def test_cross_provider_independent_agreement_preserves_primary_quarantine():
    value = primary_context()
    proof, _, error = resolve(
        GammaEvidenceLadder(cross_providers=[cross_provider()]), value
    )
    assert (
        proof["state"] == "CERTIFIED_CROSS_PROVIDER"
        and proof["gamma_flip"] == 106.02
        and error is None
    )
    assert value["gamma_flip_status"] == "sensitive_root" and value["gamma_flip"] == 106
    effective = {**value, "gamma_flip": proof["gamma_flip"], "gamma_evidence": proof}
    assert flashalpha_directional_bias(effective, now=NOW) == "bullish"
    effective["gamma_flip"] = 106
    assert flashalpha_directional_bias(effective, now=NOW) == "neutral"


@pytest.mark.parametrize(
    "change",
    [
        {"gamma_flip": 105},
        {"symbol": "MSFT"},
        {"provider": "flashalpha"},
        {"scope": "weekly_only"},
        {"sign_convention": "inverted"},
        {"status": "sensitive_root"},
        {"snapshot_id": None},
        {"as_of": (NOW - timedelta(minutes=5)).isoformat()},
        {"options_as_of": (NOW + timedelta(seconds=1)).isoformat()},
        {"underlying_as_of": (NOW - timedelta(seconds=90)).isoformat()},
        {
            "quality": {
                "oi_coverage": 0.99,
                "unique_stable_root": True,
                "maximum_stress_move_fraction": 0,
            }
        },
        {
            "quality": {
                "oi_coverage": 1,
                "unique_stable_root": True,
                "maximum_stress_move_fraction": 0.002,
            }
        },
        {"gamma_flip": float("nan")},
        {"gamma_flip": True},
        {"data_lineage": ["flashalpha"]},
        {"calculation_owner": "flashalpha"},
    ],
)
def test_cross_provider_must_pass_all_quality_identity_freshness_and_agreement_rules(
    change,
):
    proof, _, _ = resolve(
        GammaEvidenceLadder(cross_providers=[cross_provider(cross_estimate(**change))]),
        primary_context(),
    )
    assert proof["state"] == "UNCERTIFIED" and proof["gamma_flip"] is None


def test_ordinary_quotes_are_not_cross_provider_gamma_evidence():
    provider = SimpleNamespace(
        name="alpaca",
        gamma_estimate=lambda symbol: {
            "provider": "alpaca",
            "symbol": symbol,
            "price": 106.02,
        },
    )
    proof, _, _ = resolve(
        GammaEvidenceLadder(cross_providers=[provider]), primary_context()
    )
    assert proof["state"] == "UNCERTIFIED"


def test_fallback_does_not_repair_other_invalid_primary_fields():
    primary = Primary()
    value = primary_context()
    value["put_wall"] = 110
    provider = cross_provider()
    proof, _, error = resolve(
        GammaEvidenceLadder(cross_providers=[provider]), value, primary
    )
    assert (
        proof["state"] == "UNCERTIFIED"
        and proof["reason"] == "supporting_provider_evidence_invalid"
    )
    assert primary.calls == 0 and error == "provider_incomplete"


def test_quota_reserved_skips_quality_requery():
    primary = Primary()
    primary.telemetry = {"remaining": 3}
    proof, _, _ = resolve(GammaEvidenceLadder(), primary_context(), primary)
    assert primary.calls == 0 and any(
        row.get("reason") == "quota_reserved" for row in proof["attempts"]
    )


def test_certificates_are_expiring_immutable_symbol_bound_records():
    proof, _, _ = resolve(
        GammaEvidenceLadder(cross_providers=[cross_provider()]), primary_context()
    )
    for symbol, at in [("MSFT", NOW), ("SNOW", NOW + timedelta(seconds=120))]:
        with pytest.raises(GammaQualityError):
            validate_certificate(proof, symbol=symbol, now=at)
    changed = deepcopy(proof)
    changed["gamma_flip"] = 322.704
    with pytest.raises(GammaQualityError, match="changed"):
        validate_certificate(changed, symbol="SNOW", now=NOW)


def synthetic_chain():
    from math import erf, exp, log, sqrt

    def price(s, k, v, t, r, side):
        d1 = (log(s / k) + (r + v * v / 2) * t) / (v * sqrt(t))
        d2 = d1 - v * sqrt(t)
        n = lambda x: (1 + erf(x / sqrt(2))) / 2
        call = s * n(d1) - k * exp(-r * t) * n(d2)
        return call if side == "call" else call - s + k * exp(-r * t)

    expiry = NOW + timedelta(days=30)
    years = 30 / 365
    rows = []
    for i in range(100):
        k = 80 + i * 40 / 99
        for side in ("call", "put"):
            mid = price(100, k, 0.35, years, 0.02, side)
            rows.append(
                {
                    "symbol": f"SNOW-{i}-{side}",
                    "underlying_symbol": "SNOW",
                    "type": side,
                    "open_interest": 1000
                    if (side == "put" and k < 95) or (side == "call" and k > 105)
                    else 0,
                    "open_interest_date": "2026-08-26",
                    "strike": k,
                    "multiplier": 100,
                    "adjusted": False,
                    "expires_at": expiry.isoformat(),
                    "quote_as_of": NOW.isoformat(),
                    "bid": mid * 0.99,
                    "ask": mid * 1.01,
                    "iv": 0.35,
                    "gamma": bs_gamma(100, k, 0.35, years, 0.02, 0),
                }
            )
    return {
        "symbol": "SNOW",
        "provider": "independent_test_chain",
        "feed": "opra",
        "complete": True,
        "scope": "full_chain",
        "model": MODEL,
        "sign_convention": CONVENTION,
        "as_of": NOW.isoformat(),
        "underlying_as_of": NOW.isoformat(),
        "underlying_price": 100,
        "pricing_inputs": {
            "source": "synthetic_verified_rates",
            "as_of": NOW.isoformat(),
            "risk_free_rate": 0.02,
            "dividend_yield": 0,
        },
        "calendar": calendar_rows(
            (NOW - timedelta(days=14)).date().isoformat(), NOW.date().isoformat()
        ),
        "expected_contract_count": len(rows),
        "contracts": rows,
    }


def test_black_scholes_gamma_independent_known_value():
    assert bs_gamma(100, 100, 0.2, 1, 0.05, 0) == pytest.approx(
        0.0187620173458469, rel=1e-12
    )


def test_reconstruction_reprices_complete_chain_and_stresses_each_strike():
    chain = synthetic_chain()
    copy = deepcopy(chain)
    result = reconstruct(chain, symbol="SNOW", now=NOW)
    assert 95 < result["gamma_flip"] < 102
    assert result["quality"]["stress_variants"] > 100
    assert result["quality"]["maximum_stress_move_fraction"] <= 0.001
    assert chain == copy
    value = primary_context(flip=result["gamma_flip"])
    value["underlying_price"] = 100
    value["net_gex"] = result["net_gex"]
    provider = SimpleNamespace(
        name=chain["provider"], chain=lambda symbol: deepcopy(chain)
    )
    proof, _, error = resolve(GammaEvidenceLadder(chain_provider=provider), value)
    assert proof["state"] == "CERTIFIED_RECONSTRUCTED" and error is None
    assert proof["gamma_flip"] == result["gamma_flip"]


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("indicative", "real_time"),
        ("incomplete", "incomplete"),
        ("duplicate", "duplicate"),
        ("missing_oi", "invalid_number"),
        ("stale_oi", "open_interest"),
        ("missing_iv", "invalid_number"),
        ("stale_quote", "stale_or_future"),
        ("adjusted", "adjusted"),
        ("wrong_gamma", "model_disagreement"),
        ("missing_rates", "pricing_inputs"),
        ("partial_scope", "incomplete"),
        ("inverted", "sign_convention"),
        ("stale_rates", "stale_or_future"),
        ("unknown_calendar", "calendar"),
        ("count", "count_incomplete"),
    ],
)
def test_reconstruction_never_fills_missing_or_invalid_inputs(mutation, reason):
    value = synthetic_chain()
    row = next(r for r in value["contracts"] if r["open_interest"])
    if mutation == "indicative":
        value["feed"] = "indicative"
    if mutation == "incomplete":
        value["complete"] = False
    if mutation == "duplicate":
        value["contracts"][1]["symbol"] = value["contracts"][0]["symbol"]
    if mutation == "missing_oi":
        row["open_interest"] = None
    if mutation == "stale_oi":
        row["open_interest_date"] = "2026-08-25"
    if mutation == "missing_iv":
        row["iv"] = None
    if mutation == "stale_quote":
        row["quote_as_of"] = (NOW - timedelta(minutes=3)).isoformat()
    if mutation == "adjusted":
        row["adjusted"] = True
    if mutation == "wrong_gamma":
        row["gamma"] *= 3
    if mutation == "missing_rates":
        value["pricing_inputs"] = None
    if mutation == "partial_scope":
        value["scope"] = "weekly_only"
    if mutation == "inverted":
        value["sign_convention"] = "inverse"
    if mutation == "stale_rates":
        value["pricing_inputs"]["as_of"] = (NOW - timedelta(days=2)).isoformat()
    if mutation == "unknown_calendar":
        value["calendar"] = None
    if mutation == "count":
        value["expected_contract_count"] += 1
    with pytest.raises(GammaQualityError, match=reason):
        reconstruct(value, symbol="SNOW", now=NOW)


def test_uncertified_gamma_continues_candles_but_missing_confluence_blocks():
    provider = Primary()
    coordinator = StockMarketIntelligenceCoordinator(
        Alpaca(), Quiver(), Finnhub(), provider, environment={}
    )
    result = asyncio.run(coordinator.analyse("SNOW", now=NOW))
    assert result["gamma_evidence"]["state"] == "UNCERTIFIED"
    assert result["gamma_flip"] is None and not publication_allowed(result)
    assert result["gamma_evidence"]["degradation_allowed"] is True
    assert "candle_diagnostics" in result
    assert "uncertified_gamma_requires_full_independent_confluence" in result["reasons"]
    assert analysis_trace(result)["gamma_evidence"] == result["gamma_evidence"]


def test_reconstruction_rejects_no_crossing_instead_of_manufacturing_a_root():
    value = synthetic_chain()
    for row in value["contracts"]:
        row["open_interest"] = (
            (1000 if row["type"] == "call" else 1) if 95 <= row["strike"] <= 105 else 0
        )
    with pytest.raises(GammaQualityError, match="no_boundary"):
        reconstruct(value, symbol="SNOW", now=NOW)


def test_single_strike_stress_rejects_concentrated_sensitive_root():
    value = synthetic_chain()
    for row in value["contracts"]:
        row["open_interest"] = 0
    selected = [
        value["contracts"][1],
        value["contracts"][21],
        value["contracts"][-2],
        value["contracts"][-22],
    ]
    for row in selected:
        row["open_interest"] = 1000
    with pytest.raises(GammaQualityError, match="sensitive_root"):
        reconstruct(value, symbol="SNOW", now=NOW)


def test_quote_mid_must_agree_with_independent_pricing_model():
    value = synthetic_chain()
    row = next(row for row in value["contracts"] if row["open_interest"])
    row["bid"] *= 10
    row["ask"] *= 10
    with pytest.raises(GammaQualityError, match="option_price_model_disagreement"):
        reconstruct(value, symbol="SNOW", now=NOW)


def test_ladder_never_leaks_raw_provider_error_text():
    def broken(symbol):
        raise GammaQualityError("PRIVATE TOKEN BODY")

    ladder = GammaEvidenceLadder(
        chain_provider=SimpleNamespace(name="independent_test_chain", chain=broken)
    )
    proof, _, _ = resolve(ladder, primary_context())
    assert "PRIVATE" not in str(proof) and proof["state"] == "UNCERTIFIED"

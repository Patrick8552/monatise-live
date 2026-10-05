"""Offline benchmark and finite-difference checks; no live certification."""

from dataclasses import replace
from datetime import timedelta

import pytest

from monatise.application.gold_options import (
    GoldOptionDefinition,
    OptionObservation,
    american_futures,
    black76,
    european_greeks,
    gamma_roots,
    implied_volatility,
    option_analytics,
)
from tests.test_databento_gold import NOW


@pytest.mark.parametrize("kind", ["C", "P"])
def test_black76_benchmark_and_finite_difference_greeks(kind):
    result = black76(100, 100, 1, 0.05, 0.2, kind)
    assert result == pytest.approx(7.5770821464, rel=1e-8)
    h = 0.01
    p = lambda f: black76(f, 100, 1, 0.05, 0.2, kind)
    g = european_greeks(100, 100, 1, 0.05, 0.2, kind)
    assert g["delta"] == pytest.approx((p(100 + h) - p(100 - h)) / (2 * h), rel=1e-5)
    assert g["gamma"] == pytest.approx(
        (p(100 + h) - 2 * p(100) + p(100 - h)) / h**2, rel=1e-5
    )
    h = 0.0001
    vega = (
        black76(100, 100, 1, 0.05, 0.2 + h, kind)
        - black76(100, 100, 1, 0.05, 0.2 - h, kind)
    ) / (2 * h)
    assert g["vega"] == pytest.approx(vega, rel=1e-5)
    iv = implied_volatility(
        result, future=100, strike=100, years=1, rate=0.05, kind=kind, style="European"
    )
    assert iv == pytest.approx(0.2, abs=1e-7)


@pytest.mark.parametrize("kind", ["C", "P"])
def test_american_tree_no_early_exercise_benchmark_and_american_premium(kind):
    # At zero discount, early exercise of a futures option adds no value.
    european = black76(100, 100, 1, 0, 0.2, kind)
    assert american_futures(100, 100, 1, 0, 0.2, kind, steps=800) == pytest.approx(
        european, abs=0.01
    )
    a = american_futures(100, 100, 1, 0.05, 0.2, kind)
    assert a >= black76(100, 100, 1, 0.05, 0.2, kind) - 0.01
    assert implied_volatility(
        a, future=100, strike=100, years=1, rate=0.05, kind=kind, style="American"
    ) == pytest.approx(0.2, abs=1e-7)


@pytest.mark.parametrize("premium", [0, -1, float("nan"), 10000])
def test_impossible_iv_never_returns_zero_or_neutral(premium):
    with pytest.raises(ValueError):
        implied_volatility(
            premium,
            future=100,
            strike=100,
            years=1,
            rate=0.05,
            kind="C",
            style="European",
        )


def observation():
    d = GoldOptionDefinition(
        200,
        "OG_SYNTHETIC",
        "OG",
        "C",
        2500,
        NOW + timedelta(days=30),
        100,
        "GCZ6",
        NOW + timedelta(days=60),
        NOW - timedelta(days=1),
        "American",
        100,
    )
    premium = american_futures(2500, 2500, 30 / 365, 0.04, 0.2, "C")
    return OptionObservation(
        d, premium - 0.1, premium + 0.1, 2500, NOW, NOW, 0.04, NOW, None, None, None
    )


def test_missing_oi_remains_null_and_american_greeks_unavailable():
    r = option_analytics(observation(), now=NOW)
    assert r["oi"] is None and r["greeks"] is None and r["gamma_flip"] is None
    assert (
        r["gil_state"] == "DEGRADED"
        and r["direction"] is None
        and not r["oi_is_dealer_inventory"]
    )


@pytest.mark.parametrize(
    "change",
    [
        {"bid": -1},
        {"ask": 1},
        {"quote_as_of": NOW - timedelta(seconds=31)},
        {"underlying_as_of": NOW - timedelta(seconds=2)},
        {"oi": 1},
        {
            "oi": 1,
            "oi_trade_date": NOW.date(),
            "oi_published_at": NOW + timedelta(hours=1),
        },
    ],
)
def test_bad_or_delayed_inputs_rejected_before_calculation(change):
    with pytest.raises(ValueError):
        option_analytics(replace(observation(), **change), now=NOW)


def test_explicit_roots_no_root_multiple_unstable_and_coverage():
    args = {
        "low": 10,
        "high": 20,
        "coverage": 1,
        "position_assumption": "synthetic signed model; inventory unknown",
        "steps": 11,
    }
    r = gamma_roots(lambda x: x - 15.123, **args)
    assert (
        r["root"] == pytest.approx(15.123, abs=1e-5) and not r["dealer_inventory_known"]
    )
    assert gamma_roots(lambda x: 1, **args)["reason"] == "no_root"
    assert (
        gamma_roots(lambda x: (x - 12.123) * (x - 18.123), **args)["reason"]
        == "multiple_roots"
    )
    assert gamma_roots(lambda x: 0, **args)["root"] is None
    assert gamma_roots(lambda x: 1e-10 * (x - 15), **args)["root"] is None
    assert gamma_roots(lambda x: x - 15, **{**args, "coverage": 0.5})["root"] is None
    assert gamma_roots(lambda x: float("nan"), **args)["root"] is None

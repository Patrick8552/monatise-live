"""Offline Gold futures-option normalization and explicitly labelled models.

No dealer inventory is inferred from OI. Supported standard OG American options
use a futures martingale CRR tree; Black-76 is only an explicitly European
benchmark. Weekly/exotic conventions require a separate verified specification.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from math import erf, exp, isfinite, log, pi, sqrt

from monatise.adapters.databento_gold import ns_time, price


def _inputs(future, strike, years, rate, volatility, kind):
    values = (future, strike, years, rate, volatility)
    if (
        any(isinstance(v, bool) for v in values)
        or not all(isfinite(v) for v in values)
        or min(future, strike, years, volatility) <= 0
        or years > 10
        or not -0.1 <= rate <= 0.5
        or not 0.0001 <= volatility <= 5
        or kind not in {"C", "P"}
    ):
        raise ValueError("unsupported option pricing inputs")


def black76(future, strike, years, rate, volatility, kind):
    _inputs(future, strike, years, rate, volatility, kind)
    d1 = (log(future / strike) + volatility * volatility * years / 2) / (
        volatility * sqrt(years)
    )
    d2 = d1 - volatility * sqrt(years)
    cdf = lambda x: (1 + erf(x / sqrt(2))) / 2
    if kind == "C":
        return exp(-rate * years) * (future * cdf(d1) - strike * cdf(d2))
    return exp(-rate * years) * (strike * cdf(-d2) - future * cdf(-d1))


def american_futures(future, strike, years, rate, volatility, kind, *, steps=400):
    _inputs(future, strike, years, rate, volatility, kind)
    if not 50 <= steps <= 1600:
        raise ValueError("bounded binomial tree steps required")
    dt = years / steps
    u = exp(volatility * sqrt(dt))
    d = 1 / u
    probability = (1 - d) / (
        u - d
    )  # futures is a martingale under risk-neutral measure
    if not 0 < probability < 1:
        raise ValueError("binomial probability invalid")
    discount = exp(-rate * dt)
    sign = 1 if kind == "C" else -1
    nodes = [
        max(0.0, sign * (future * u**j * d ** (steps - j) - strike))
        for j in range(steps + 1)
    ]
    for n in range(steps - 1, -1, -1):
        nodes = [
            max(
                sign * (future * u**j * d ** (n - j) - strike),
                discount * (probability * nodes[j + 1] + (1 - probability) * nodes[j]),
            )
            for j in range(n + 1)
        ]
    result = nodes[0]
    if not isfinite(result) or result < 0:
        raise ValueError("option tree failed")
    return result


def implied_volatility(premium, *, future, strike, years, rate, kind, style):
    if not isfinite(premium) or premium <= 0 or style not in {"American", "European"}:
        raise ValueError("unusable premium or exercise convention")
    model = american_futures if style == "American" else black76
    low, high = 0.0001, 5.0
    floor, ceiling = (
        model(future, strike, years, rate, low, kind),
        model(future, strike, years, rate, high, kind),
    )
    if not floor < premium < ceiling:
        raise ValueError("premium violates supported model bounds")
    for _ in range(70):
        middle = (low + high) / 2
        value = model(future, strike, years, rate, middle, kind)
        if abs(value - premium) <= 1e-7:
            return middle
        if value < premium:
            low = middle
        else:
            high = middle
    raise ValueError("IV solver did not converge")


def european_greeks(future, strike, years, rate, volatility, kind):
    _inputs(future, strike, years, rate, volatility, kind)
    d1 = (log(future / strike) + volatility * volatility * years / 2) / (
        volatility * sqrt(years)
    )
    cdf = (1 + erf(d1 / sqrt(2))) / 2
    density = exp(-d1 * d1 / 2) / sqrt(2 * pi)
    return {
        "delta": exp(-rate * years) * (cdf if kind == "C" else cdf - 1),
        "gamma": exp(-rate * years) * density / (future * volatility * sqrt(years)),
        "vega": exp(-rate * years) * future * density * sqrt(years),
    }


@dataclass(frozen=True)
class GoldOptionDefinition:
    instrument_id: int
    raw_symbol: str
    family: str
    kind: str
    strike: float
    expiry: datetime
    underlying_id: int
    underlying_contract: str
    underlying_expiry: datetime
    definition_as_of: datetime
    style: str
    multiplier: float


def normalize_option(record, *, futures, publishers, now, convention):
    # Convention must come from a reviewed contract specification, never from
    # a root-name guess. Standard OG only in this first implementation.
    if convention != {
        "family": "OG",
        "style": "American",
        "settlement": "future_delivery",
        "currency": "USD",
        "multiplier": 100,
    }:
        raise ValueError("unsupported or unverified Gold option convention")
    if (
        publishers.get(record.publisher_id) != ("GLBX.MDP3", "XCEC")
        or str(record.asset) != "OG"
        or str(record.instrument_class) not in {"C", "P"}
        or record.leg_count != 0
        or str(record.user_defined_instrument) != "N"
    ):
        raise ValueError("unsupported option family, strategy or publisher")
    underlying = futures.get(record.underlying_id)
    expiry, definition_at, received = (
        ns_time(record.expiration),
        ns_time(record.ts_event),
        ns_time(record.ts_recv),
    )
    if (
        underlying is None
        or not definition_at <= received <= now < expiry <= underlying.expiry
        or underlying.available_at > now
    ):
        raise ValueError("option underlying/expiry/point-in-time join failed")
    if (
        str(record.currency) != "USD"
        or str(record.strike_price_currency) != "USD"
        or price(record.display_factor) != 1
        or str(record.security_update_action) not in {"A", "M"}
    ):
        raise ValueError("contradictory option currency, scale or definition")
    return GoldOptionDefinition(
        record.instrument_id,
        str(record.raw_symbol),
        "OG",
        str(record.instrument_class),
        float(price(record.strike_price)),
        expiry,
        underlying.instrument_id,
        underlying.raw_symbol,
        underlying.expiry,
        received,
        "American",
        100.0,
    )


@dataclass(frozen=True)
class OptionObservation:
    definition: GoldOptionDefinition
    bid: float
    ask: float
    future_mid: float
    quote_as_of: datetime
    underlying_as_of: datetime
    rate: float
    rate_as_of: datetime
    oi: int | None
    oi_trade_date: date | None
    oi_published_at: datetime | None

    def validate(self, now):
        if (
            any(
                not isfinite(v)
                for v in (self.bid, self.ask, self.future_mid, self.rate)
            )
            or not 0 < self.bid <= self.ask
            or self.future_mid <= 0
            or self.ask - self.bid > max(0.1, 0.2 * (self.bid + self.ask) / 2)
        ):
            raise ValueError("crossed, one-sided or wide option quote")
        if any(
            t.tzinfo is None
            for t in (
                now,
                self.quote_as_of,
                self.underlying_as_of,
                self.rate_as_of,
                self.definition.definition_as_of,
                self.definition.expiry,
            )
        ):
            raise ValueError("option input timezones required")
        if any(
            not timedelta(0) <= now - t <= timedelta(seconds=30)
            for t in (self.quote_as_of, self.underlying_as_of)
        ) or abs(self.quote_as_of - self.underlying_as_of) > timedelta(seconds=1):
            raise ValueError("stale or asynchronous option leg")
        if (
            not self.rate_as_of <= now < self.definition.expiry
            or now - self.rate_as_of > timedelta(days=1)
            or self.definition.definition_as_of > now
        ):
            raise ValueError("definition/rate/expiry unavailable point-in-time")
        if self.oi is not None and (
            isinstance(self.oi, bool)
            or not isinstance(self.oi, int)
            or self.oi < 0
            or self.oi_trade_date is None
            or self.oi_published_at is None
            or self.oi_published_at.tzinfo is None
            or self.oi_published_at > now
            or self.oi_trade_date > self.oi_published_at.date()
            or now.date() - self.oi_trade_date > timedelta(days=4)
        ):
            raise ValueError("OI unavailable, delayed, stale or contradictory")


def option_analytics(observation, *, now):
    observation.validate(now)
    definition = observation.definition
    years = (definition.expiry - now).total_seconds() / (
        365 * 86400
    )  # declared ACT/365F
    premium = (observation.bid + observation.ask) / 2
    iv = implied_volatility(
        premium,
        future=observation.future_mid,
        strike=definition.strike,
        years=years,
        rate=observation.rate,
        kind=definition.kind,
        style=definition.style,
    )
    # American tree prices are supported. American gamma stability/certification
    # is not established by a price solver; do not invent Greeks or dealer roots.
    greeks = (
        european_greeks(
            observation.future_mid,
            definition.strike,
            years,
            observation.rate,
            iv,
            definition.kind,
        )
        if definition.style == "European"
        else None
    )
    return {
        "iv": iv,
        "greeks": greeks,
        "model": "futures_CRR_400" if definition.style == "American" else "Black76",
        "time_convention": "ACT/365F",
        "gil_state": "DEGRADED" if greeks is None else "CONFIRMED",
        "model_uncertainty": "american_greeks_not_certified"
        if greeks is None
        else "european_verified_convention_required",
        "oi": observation.oi,
        "oi_is_dealer_inventory": False,
        "direction": None,
        "quote_as_of": observation.quote_as_of.isoformat(),
        "underlying_as_of": observation.underlying_as_of.isoformat(),
        "oi_trade_date": observation.oi_trade_date.isoformat()
        if observation.oi_trade_date
        else None,
        "oi_published_at": observation.oi_published_at.isoformat()
        if observation.oi_published_at
        else None,
        "definition_as_of": definition.definition_as_of.isoformat(),
        "calculated_at": now.isoformat(),
        "gamma_flip": None,
        "gamma_flip_reason": "signed_dealer_positions_unavailable",
    }


def gamma_roots(
    exposure, *, low, high, coverage, position_assumption, steps=100, tolerance=1e-6
):
    """Roots of an explicit model function, never a strike or inferred inventory."""
    missing = {"root": None, "roots": [], "gil_state": "UNVERIFIED"}
    if not position_assumption or not 0.9 <= coverage <= 1:
        return {**missing, "reason": "position_assumption_or_coverage_unavailable"}
    if (
        not isfinite(low)
        or not isfinite(high)
        or not 0 < low < high
        or not 10 <= steps <= 1000
        or not 0 < tolerance < 1
    ):
        raise ValueError("invalid root search bounds")
    points = [low + (high - low) * i / steps for i in range(steps + 1)]
    values = [exposure(p) for p in points]
    if any(not isfinite(v) for v in values):
        return {**missing, "reason": "model_not_finite"}
    roots = []
    if any(abs(v) <= tolerance for v in values):
        # Zero plateaux or a root exactly on a grid point need an explicit
        # sensitivity analysis, not a nearest-strike fallback.
        return {**missing, "reason": "unstable_or_grid_root"}
    for i in range(steps):
        if values[i] * values[i + 1] >= 0:
            continue
        a, b, fa = points[i], points[i + 1], values[i]
        for _ in range(70):
            middle = (a + b) / 2
            fm = exposure(middle)
            if not isfinite(fm):
                return {**missing, "reason": "model_not_finite"}
            if b - a <= tolerance:
                break
            if fa * fm <= 0:
                b = middle
            else:
                a, fa = middle, fm
        root = (a + b) / 2
        if abs(exposure(root)) > max(
            tolerance, max(abs(values[i]), abs(values[i + 1])) * 0.001
        ):
            return {**missing, "reason": "root_residual_unstable"}
        roots.append(root)
    if len(roots) != 1:
        return {
            **missing,
            "roots": roots,
            "reason": "no_root" if not roots else "multiple_roots",
        }
    root = roots[0]
    h = max(tolerance * 10, root * 1e-5)
    slope = (exposure(root + h) - exposure(root - h)) / (2 * h)
    if not isfinite(slope) or abs(slope) <= tolerance:
        return {**missing, "roots": roots, "reason": "unstable_root"}
    return {
        "root": root,
        "roots": roots,
        "gil_state": "CONFIRMED",
        "position_assumption": position_assumption,
        "dealer_inventory_known": False,
        "direction": None,
    }

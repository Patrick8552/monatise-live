"""Independent, bounded gamma reconstruction from a complete qualified book.

Certification describes evidence and numerical stability, never profitability.
The model is explicit: constant-IV Black-Scholes, call-positive/put-negative OI.
Missing pricing inputs are rejected, not inferred from a withheld primary root.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from monatise.application.hierarchy.stock_sessions import StockSessionCalendar, NEW_YORK
from time import monotonic

CONVENTION = "call_positive_put_negative_v1"
MODEL = "black_scholes_constant_iv_v1"


QUALITY_CODES = frozenset(
    [
        "independent_confluence_or_gamma_required",
        "confidence_evidence_missing",
        "confidence_evidence_changed",
        "primary_provenance_incomplete",
        "adjusted_contract_unsupported",
        "ambiguous_multiple_roots",
        "chain_collection_budget",
        "chain_count_incomplete",
        "chain_duplicate_or_malformed_contract",
        "chain_identity_mismatch",
        "chain_incomplete",
        "chain_pagination_incomplete",
        "chain_pagination_invalid",
        "chain_payload_invalid",
        "chain_snapshots_incomplete",
        "chain_timestamp_misalignment",
        "contract_identity_mismatch",
        "contract_side_unknown",
        "cross_provider_certificate_invalid",
        "cross_provider_independence_unverified",
        "cross_provider_provenance_missing",
        "cross_provider_quality_insufficient",
        "duplicate_or_missing_contract",
        "expired_contract",
        "gamma_certificate_changed",
        "gamma_certificate_expired_or_future",
        "gamma_certificate_missing_or_uncertified",
        "gamma_model_disagreement",
        "gamma_regime_orientation_unverified",
        "independent_gamma_disagreement",
        "independent_gex_provider_required",
        "independent_gex_sign_disagreement",
        "independent_real_time_feed_required",
        "insufficient_call_put_strike_coverage",
        "insufficient_quote_quality",
        "invalid_implied_volatility",
        "invalid_number",
        "invalid_timestamp",
        "missing_timestamp",
        "model_or_sign_convention_unverified",
        "naive_timestamp",
        "no_boundary",
        "no_option_time_value",
        "non_positive_number",
        "open_interest_calendar_unverified",
        "open_interest_missing_or_stale",
        "opra_access_denied",
        "opra_access_denied_backoff",
        "option_price_model_disagreement",
        "options_provider_unavailable",
        "pricing_inputs_out_of_range",
        "primary_requery_not_newly_certified",
        "reconstruction_work_budget",
        "root_path_or_local_coverage_unverified",
        "sensitive_root",
        "stale_or_future_evidence",
        "underlying_price_disagreement",
        "verified_pricing_inputs_unavailable",
    ]
)


class GammaQualityError(ValueError):
    def __init__(self, code):
        super().__init__(code if code in QUALITY_CODES else "gamma_quality_rejected")


def number(value, *, positive=False):
    if (
        isinstance(value, bool)
        or not isinstance(value, (float, int))
        or not math.isfinite(value)
    ):
        raise GammaQualityError("invalid_number")
    if positive and value <= 0:
        raise GammaQualityError("non_positive_number")
    return float(value)


def clock(value):
    if not isinstance(value, str):
        raise GammaQualityError("missing_timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GammaQualityError("invalid_timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GammaQualityError("naive_timestamp")
    return parsed


def fresh(value, now, seconds):
    stamp = clock(value)
    if not 0 <= (now - stamp).total_seconds() <= seconds:
        raise GammaQualityError("stale_or_future_evidence")
    return stamp


@dataclass(frozen=True)
class GammaQualityPolicy:
    version: str = "independent-gamma-v1"
    maximum_age_seconds: int = 120
    maximum_timestamp_skew_seconds: int = 60
    agreement_fraction: float = 0.0025
    maximum_stress_move_fraction: float = 0.001
    maximum_contracts: int = 4000
    maximum_strikes: int = 256
    maximum_compute_seconds: float = 8.0


POLICY = GammaQualityPolicy()


def bs_gamma(spot, strike, volatility, years, rate, dividend):
    root_t = math.sqrt(years)
    d1 = (
        math.log(spot / strike)
        + (rate - dividend + volatility * volatility / 2) * years
    ) / (volatility * root_t)
    return math.exp(-dividend * years - d1 * d1 / 2) / (
        math.sqrt(2 * math.pi) * spot * volatility * root_t
    )


def bs_price(spot, strike, volatility, years, rate, dividend, side):
    scale = volatility * math.sqrt(years)
    d1 = (
        math.log(spot / strike) + (rate - dividend + volatility**2 / 2) * years
    ) / scale
    d2 = d1 - scale

    def normal(x):
        return (1 + math.erf(x / math.sqrt(2))) / 2

    discounted_spot, discounted_strike = (
        spot * math.exp(-dividend * years),
        strike * math.exp(-rate * years),
    )
    call = discounted_spot * normal(d1) - discounted_strike * normal(d2)
    return call if side == "call" else call - discounted_spot + discounted_strike


def reconstruct(chain, *, symbol, now, policy=POLICY):
    """Return independent level + evidence, or a specific fail-closed reason."""
    started = monotonic()

    def budget():
        if monotonic() - started > policy.maximum_compute_seconds:
            raise GammaQualityError("reconstruction_work_budget")

    if not isinstance(chain, dict) or chain.get("symbol") != symbol:
        raise GammaQualityError("chain_identity_mismatch")
    if chain.get("feed") != "opra" or chain.get("provider") in {None, "flashalpha"}:
        raise GammaQualityError("independent_real_time_feed_required")
    if chain.get("complete") is not True or chain.get("scope") != "full_chain":
        raise GammaQualityError("chain_incomplete")
    if chain.get("sign_convention") != CONVENTION or chain.get("model") != MODEL:
        raise GammaQualityError("model_or_sign_convention_unverified")
    spot = number(chain.get("underlying_price"), positive=True)
    underlying_at = fresh(
        chain.get("underlying_as_of"), now, policy.maximum_age_seconds
    )
    stamps = [underlying_at, fresh(chain.get("as_of"), now, policy.maximum_age_seconds)]
    # Rates/dividend inputs must be independently supplied and dated. The
    # Alpaca adapter deliberately does not invent values for these fields.
    pricing = chain.get("pricing_inputs")
    if not isinstance(pricing, dict) or not pricing.get("source"):
        raise GammaQualityError("verified_pricing_inputs_unavailable")
    fresh(pricing.get("as_of"), now, 86400)
    rate, dividend = (
        number(pricing.get("risk_free_rate")),
        number(pricing.get("dividend_yield")),
    )
    if not -0.1 <= rate <= 1 or not 0 <= dividend <= 1:
        raise GammaQualityError("pricing_inputs_out_of_range")
    try:
        calendar = StockSessionCalendar.from_provider(
            chain.get("calendar"),
            start=(now - timedelta(days=14)).astimezone(NEW_YORK).date(),
            end=now.astimezone(NEW_YORK).date(),
        )
        completed = [session for session in calendar.sessions if session.closes < now]
        expected_oi = completed[-1].day.isoformat()
    except (ValueError, IndexError) as exc:
        raise GammaQualityError("open_interest_calendar_unverified") from exc
    rows = chain.get("contracts")
    if (
        not isinstance(rows, list)
        or not 4 <= len(rows) <= policy.maximum_contracts
        or chain.get("expected_contract_count") != len(rows)
    ):
        raise GammaQualityError("chain_count_incomplete")
    seen, sides, components, strikes = set(), set(), [], set()
    for row in rows:
        budget()
        if not isinstance(row, dict) or row.get("underlying_symbol") != symbol:
            raise GammaQualityError("contract_identity_mismatch")
        identity = row.get("symbol")
        if not isinstance(identity, str) or not identity or identity in seen:
            raise GammaQualityError("duplicate_or_missing_contract")
        seen.add(identity)
        side = row.get("type")
        if side not in {"call", "put"}:
            raise GammaQualityError("contract_side_unknown")
        oi = number(row.get("open_interest"))
        if (
            oi < 0
            or not oi.is_integer()
            or row.get("open_interest_date") != expected_oi
        ):
            raise GammaQualityError("open_interest_missing_or_stale")
        # Zero OI contributes nothing but still requires verified metadata.
        strike = number(row.get("strike"), positive=True)
        multiplier = number(row.get("multiplier"), positive=True)
        if multiplier != 100 or row.get("adjusted") is not False:
            raise GammaQualityError("adjusted_contract_unsupported")
        expires = clock(row.get("expires_at"))
        if expires <= now:
            raise GammaQualityError("expired_contract")
        if oi == 0:
            continue
        sides.add(side)
        strikes.add(strike)
        stamp = fresh(row.get("quote_as_of"), now, policy.maximum_age_seconds)
        if (
            abs((stamp - underlying_at).total_seconds())
            > policy.maximum_timestamp_skew_seconds
        ):
            raise GammaQualityError("chain_timestamp_misalignment")
        stamps.append(stamp)
        bid, ask = (
            number(row.get("bid"), positive=True),
            number(row.get("ask"), positive=True),
        )
        if ask < bid or (ask - bid) / ((ask + bid) / 2) > 0.25:
            raise GammaQualityError("insufficient_quote_quality")
        vol = number(row.get("iv"), positive=True)
        years = (expires - now).total_seconds() / (365 * 86400)
        if not 0.001 <= vol <= 5:
            raise GammaQualityError("invalid_implied_volatility")
        intrinsic = max(spot - strike, 0) if side == "call" else max(strike - spot, 0)
        if (bid + ask) / 2 <= intrinsic:
            raise GammaQualityError("no_option_time_value")
        modeled_price = bs_price(spot, strike, vol, years, rate, dividend, side)
        allowance = max(0.01, (bid + ask) / 2 * 0.05)
        if not bid - allowance <= modeled_price <= ask + allowance:
            raise GammaQualityError("option_price_model_disagreement")
        supplied = number(row.get("gamma"), positive=True)
        calculated = bs_gamma(spot, strike, vol, years, rate, dividend)
        if abs(calculated - supplied) > max(calculated * 0.05, 1e-10):
            raise GammaQualityError("gamma_model_disagreement")
        components.append(
            (strike, vol, years, oi * multiplier * (1 if side == "call" else -1))
        )
    if sides != {"call", "put"} or len(strikes) < 3:
        raise GammaQualityError("insufficient_call_put_strike_coverage")
    if len(strikes) > policy.maximum_strikes:
        raise GammaQualityError("reconstruction_work_budget")

    def values(spot_value):
        by_strike = {}
        for strike, vol, years, weight in components:
            value = (
                bs_gamma(spot_value, strike, vol, years, rate, dividend)
                * weight
                * spot_value**2
                * 0.01
            )
            by_strike[strike] = by_strike.get(strike, 0.0) + value
        return by_strike

    def net(spot_value, stress_strike=None, change=0.0):
        v = values(spot_value)
        return sum(v.values()) + v.get(stress_strike, 0) * change

    def root(brackets, stress_strike=None, change=0.0):
        if len(brackets) != 1:
            raise GammaQualityError(
                "no_boundary" if not brackets else "ambiguous_multiple_roots"
            )
        low, high = brackets[0]
        # A stock directional gamma context requires negative -> positive.
        if (
            net(low, stress_strike, change) >= 0
            or net(high, stress_strike, change) <= 0
        ):
            raise GammaQualityError("gamma_regime_orientation_unverified")
        for _ in range(40):
            budget()
            middle = (low + high) / 2
            if net(middle, stress_strike, change) > 0:
                high = middle
            else:
                low = middle
        return (low + high) / 2

    def crossings(xs, ys):
        # An exactly zero sampled point is not certified as a flat root.
        nonzero = [(x, y) for x, y in zip(xs, ys) if y != 0]
        return [(a[0], b[0]) for a, b in zip(nonzero, nonzero[1:]) if a[1] * b[1] < 0]

    xs = [spot * (0.5 + index / 512) for index in range(513)]
    profiles = [values(x) for x in xs]
    ys = [sum(v.values()) for v in profiles]
    base = root(crossings(xs, ys))
    coarse = root(crossings(xs[::2], ys[::2]))
    if abs(base - coarse) > spot * 1e-6 or not min(strikes) < min(base, spot) <= max(
        base, spot
    ) < max(strikes):
        raise GammaQualityError("root_path_or_local_coverage_unverified")
    maximum_move = 0.0
    for strike in sorted(strikes):
        for change in (-0.25, 0.25):
            budget()
            stressed = [
                y + profile.get(strike, 0) * change for y, profile in zip(ys, profiles)
            ]
            shifted = root(crossings(xs, stressed), strike, change)
            maximum_move = max(maximum_move, abs(shifted - base) / spot)
            if maximum_move > policy.maximum_stress_move_fraction:
                raise GammaQualityError("sensitive_root")
    return {
        "gamma_flip": base,
        "underlying_price": spot,
        "provider": chain["provider"],
        "net_gex": net(spot),
        "as_of": min(stamps).isoformat(),
        "expires_at": (
            min(stamps) + timedelta(seconds=policy.maximum_age_seconds)
        ).isoformat(),
        "methodology": MODEL,
        "sign_convention": CONVENTION,
        "scope": "full_chain",
        "quality": {
            "oi_coverage": 1.0,
            "contract_count": len(rows),
            "stress_variants": len(strikes) * 2,
            "maximum_stress_move_fraction": maximum_move,
            "unique_stable_root": True,
        },
    }

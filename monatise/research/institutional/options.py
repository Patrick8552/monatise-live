"""Exact options input joins and unsigned model estimates; no GIL activation."""
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite

from monatise.application.gold_options import GoldOptionDefinition, OptionObservation, option_analytics
from monatise.research.databento.options import join_inputs, OpenInterest
from monatise.research.databento.advanced import Observation
from .models import Contract, MarketObservation, digest, encode, hash_required, number
from .mapping import dt


@dataclass(frozen=True)
class OptionConvention:
    family: str
    style: str
    definition_sha256: str
    specification_reference: str

    def __post_init__(self):
        hash_required(self.definition_sha256)
        if (self.family not in {"OG", "ES", "NQ"} or self.style not in {"American", "European"}
                or not self.specification_reference or (self.family == "OG" and self.style != "American")):
            raise ValueError("exact_reviewed_option_exercise_convention_required")


@dataclass(frozen=True)
class RateAssumption:
    annual_rate: float
    as_of_ns: int
    source_sha256: str
    methodology: str
    evidence_kind: str

    def __post_init__(self):
        from monatise.adapters.databento_identity import timestamp_ns
        timestamp_ns(self.as_of_ns)
        hash_required(self.source_sha256)
        if (isinstance(self.annual_rate, bool) or not isfinite(self.annual_rate)
                or not -.1 <= self.annual_rate <= .5 or not self.methodology
                or self.evidence_kind not in {"AUTHENTIC_ARCHIVED_RECORD", "ENGINEERING_SYNTHETIC"}):
            raise ValueError("dated_explicit_rate_assumption_required")


def _quote(value):
    m = value.contract.metadata
    return Observation(m.dataset, value.schema, m.namespace, m.publisher_id, m.instrument_id,
        m.raw_symbol, value.event_ns, value.receive_ns, value.sequence, value.flags, "N",
        value.source.record_sha256, value.payload, m.definition_sha256)


def analyze(*, option, underlying, convention, rate, cutoff_ns, open_interest=None):
    """Standard OG first; ES/NQ native option registry remains an explicit gap."""
    if (not isinstance(option, MarketObservation) or not isinstance(underlying, MarketObservation)
            or option.schema != "mbp-1" or underlying.schema != "mbp-1"
            or not isinstance(convention, OptionConvention) or not isinstance(rate, RateAssumption)
            or option.contract.metadata.product != convention.family
            or convention.definition_sha256 != option.contract.metadata.definition_sha256
            or option.contract.asset_class != "futures_option"
            or underlying.contract.asset_class != "futures"
            or option.source.evidence_kind != underlying.source.evidence_kind
            or option.source.evidence_kind != rate.evidence_kind
            or max(option.source.admission_ns,underlying.source.admission_ns) > cutoff_ns):
        raise ValueError("option_input_identity_availability_or_convention_invalid")
    if convention.family != "OG":
        raise ValueError("native_index_option_registry_not_yet_reviewed")
    m, parent = option.contract.metadata, underlying.contract.metadata
    if (m.underlying_id != parent.instrument_id or m.publisher_id != parent.publisher_id
            or m.expiration_ns > parent.expiration_ns
            or option.contract.multiplier != underlying.contract.multiplier):
        raise ValueError("option_underlying_economic_multiplier_mismatch")
    definition = GoldOptionDefinition(m.instrument_id, m.raw_symbol, m.product, m.kind,
        float(m.strike_fixed/10**9), dt(m.expiration_ns), parent.instrument_id, parent.raw_symbol,
        dt(parent.expiration_ns), dt(m.receive_ns), convention.style, float(option.contract.multiplier))
    joined = join_inputs(definition=definition, definition_available_ns=m.receive_ns,
        option_quote=_quote(option), underlying_quote=_quote(underlying),
        quote_available_ns=max(option.source.admission_ns,underlying.source.admission_ns),
        cutoff_ns=cutoff_ns, open_interest=open_interest)
    top, u = option.payload[0], underlying.payload[0]
    observed = OptionObservation(definition, float(top[0]), float(top[3]),
        float((number(u[0])+number(u[3]))/2), dt(option.receive_ns), dt(underlying.receive_ns),
        rate.annual_rate, dt(rate.as_of_ns), open_interest.contracts if open_interest else None,
        dt(open_interest.reference_ns).date() if open_interest else None,
        dt(open_interest.published_ns) if open_interest else None)
    result = option_analytics(observed, now=dt(cutoff_ns))
    return dict(status="MODEL_ESTIMATE", definition=encode(definition), iv=result['iv'],
        greeks=result['greeks'], unsigned_gamma_1pct=None, gamma_flip=None, signed_dealer_gex=None,
        model=result['model'], time_convention=result['time_convention'],
        inputs_sha256=digest(dict(join=joined,rate=rate,convention=convention)),
        evidence_kind=option.source.evidence_kind, observed_open_interest=observed.oi,
        limitation="American IV model only; American gamma is uncertified; no signed inventory from OI.",
        gil_enabled=False, execution_eligible=False)


def unsigned_european_sensitivity(*, future, strike, years, rate, volatility, kind,
                                  open_interest, multiplier, convention_reference, input_sha256):
    """Explicit European benchmark, never applied automatically to an OG contract.

    A verified index-option definition/quote join is required before this primitive
    can become authentic asset analytics. Fixture outputs remain model engineering.
    """
    from monatise.application.gold_options import european_greeks
    hash_required(input_sha256)
    if (not convention_reference or type(open_interest) is not int or open_interest < 0):
        raise ValueError("reviewed_european_convention_and_published_oi_required")
    multiplier = number(multiplier, positive=True)
    greeks = european_greeks(future,strike,years,rate,volatility,kind)
    gamma = number(greeks['gamma'])*open_interest*multiplier*number(future,positive=True)**2*number('.01')
    return dict(status="MODEL_BENCHMARK", greeks=greeks, unsigned_gamma_1pct=str(gamma),
        methodology="Black76-gamma-times-OI-times-multiplier-times-F-squared-times-0.01",
        units="USD delta-notional sensitivity per 1% futures-price move", input_sha256=input_sha256,
        convention_reference=convention_reference, signed_dealer_gex=None, gamma_flip=None,
        complete_chain=False, gil_enabled=False, execution_eligible=False)

"""Explicit native GCZ6 research reference, separate from legacy adapter defaults.

Actual DBN definitions use CME's TRYOZ and display_factor=0.1. Databento price
fields are already normalized fixed-point conventional prices: never apply the
venue display factor again. This interface changes no runtime/legacy validator.

Sources: Databento instrument-definitions and contract-notional documentation;
CME Gold futures specification. Original bytes and terms remain authoritative.
"""
from dataclasses import dataclass
from decimal import Decimal
import hashlib

from monatise.adapters.databento_gold import GCDefinition, ns_time, price
from monatise.adapters.databento_identity import timestamp_ns
from monatise.research.databento.replay import HistoricalGCReference

POLICY = "databento-native-gcz6-reference-v1"


@dataclass(frozen=True)
class NativeGCReference:
    reference: HistoricalGCReference
    native_terms: tuple
    policy_version: str = POLICY
    dbn_price_scale: int = 1_000_000_000
    conventional_currency_scale: str = "1"
    apply_display_factor_to_dbn_price: bool = False
    trading_eligible: bool = False


def reconstruct_native_gcz6(record, *, identity_policy, retrieval_ns):
    """Narrow reviewed exact-contract interface; fail closed on any contradiction."""
    import databento_dbn as dbn
    if not isinstance(record, dbn.InstrumentDefMsg):
        raise ValueError("native DBN instrument definition required")
    identity_policy.validate_contract_identity(record, publishers=identity_policy.mapping)
    if (record.publisher_id, record.instrument_id, str(record.raw_symbol)) != (1,41271,"GCZ6"):
        raise ValueError("unreviewed native contract")
    if (str(record.instrument_class) != "F" or str(record.asset) != "GC"
            or str(record.security_type) != "FUT" or record.leg_count != 0
            or str(record.user_defined_instrument) != "N"
            or str(record.currency) != "USD" or str(record.unit_of_measure) != "TRYOZ"
            or record.main_fraction != 255 or str(record.security_update_action) not in {"A","M"}):
        raise ValueError("native outright units/class/action unsupported")
    tick, size, display, amount = [price(getattr(record,k)) for k in (
        "min_price_increment","unit_of_measure_qty","display_factor","min_price_increment_amount")]
    if (tick,size,display,amount) != (Decimal(".1"),Decimal(100),Decimal(".1"),Decimal(1)):
        raise ValueError("native GC tick/size/display/amount contradiction")
    # Exact major-currency convention, no nearest-convention heuristic.
    if amount/display != tick*size:
        raise ValueError("native GC currency convention contradiction")
    event, receive, expiry, activation, retrieval = [timestamp_ns(x) for x in (
        record.ts_event,record.ts_recv,record.expiration,record.activation,retrieval_ns)]
    if (not activation <= event <= receive < expiry
            or max(receive,identity_policy.observed_at_ns) > retrieval):
        raise ValueError("native definition clocks contradictory")
    contract = GCDefinition(41271,"GCZ6",1,"XCEC",tick,size,"USD",
                            ns_time(event),ns_time(receive),ns_time(expiry))
    reference = HistoricalGCReference(contract,hashlib.sha256(bytes(record)).hexdigest(),
        event,receive,expiry,retrieval,identity_policy.sha256)
    terms=tuple((k,str(getattr(record,k))) for k in (
        "unit_of_measure","display_factor","min_price_increment","min_price_increment_amount",
        "unit_of_measure_qty","main_fraction","activation","expiration","maturity_year","maturity_month"))
    return NativeGCReference(reference,terms)

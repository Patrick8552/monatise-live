"""Isolated GC-options observation join; no GIL provider or dealer model.

Reuse standard OG economic normalization and exact underlying identities.
OI reference/publication and quote clocks stay independent. Missing OI is null.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime

from monatise.adapters.databento_identity import timestamp_ns
from monatise.research.databento.advanced import Observation
from monatise.research.databento.acquisition import canonical_hash


@dataclass(frozen=True)
class OpenInterest:
    publisher_id: int
    instrument_id: int
    contracts: int
    reference_ns: int
    published_ns: int
    available_ns: int
    record_sha256: str

    def __post_init__(self):
        import re
        for t in (self.reference_ns,self.published_ns,self.available_ns): timestamp_ns(t)
        if (type(self.contracts) is not int or not 0 <= self.contracts < 2**63-1
                or not self.reference_ns <= self.published_ns <= self.available_ns
                or not re.fullmatch(r"[a-f0-9]{64}",self.record_sha256)):
            raise ValueError("invalid published open-interest evidence")


def normalize_open_interest(record, *, available_ns):
    import databento_dbn as dbn
    if (not isinstance(record,dbn.StatMsg) or record.stat_type != dbn.StatType.OPEN_INTEREST
            or int(record.update_action) != 1):
        raise ValueError("uncorrected native open-interest statistic required")
    event,receive = timestamp_ns(record.ts_event),timestamp_ns(record.ts_recv)
    if event > receive:
        raise ValueError("OI event after receipt")
    return OpenInterest(record.publisher_id,record.instrument_id,record.quantity,
        record.ts_ref,receive,available_ns,hashlib.sha256(bytes(record)).hexdigest())


def _datetime_ns(value):
    from monatise.adapters.databento_identity import datetime_ns
    if not isinstance(value,datetime): raise ValueError("definition clock required")
    return datetime_ns(value)


def join_inputs(*, definition, definition_available_ns, option_quote, underlying_quote,
                quote_available_ns, cutoff_ns, open_interest=None, maximum_quote_age_ns=60*10**9,
                maximum_skew_ns=10**9):
    for t in (definition_available_ns,quote_available_ns,cutoff_ns): timestamp_ns(t)
    from monatise.application.gold_options import GoldOptionDefinition
    if (not isinstance(definition,GoldOptionDefinition) or definition.family != "OG"
            or definition.style != "American" or definition.kind not in {"C","P"}
            or not 0 < maximum_quote_age_ns <= 60*10**9 or not 0 <= maximum_skew_ns <= 10**9
            or not _datetime_ns(definition.definition_as_of) <= definition_available_ns <= cutoff_ns
            or not quote_available_ns <= cutoff_ns < _datetime_ns(definition.expiry)):
        raise ValueError("reviewed standard OG definition availability required")
    for quote in (option_quote,underlying_quote):
        if not isinstance(quote,Observation) or quote.schema != "mbp-1" or quote.dataset != "GLBX.MDP3":
            raise ValueError("genuine top-of-book observations required")
        if not quote.receive_ns <= quote_available_ns or not 0 <= cutoff_ns-quote.receive_ns <= maximum_quote_age_ns:
            raise ValueError("future, stale or not locally available quote")
        top = quote.payload[0]
        from decimal import Decimal
        if (top[0] is None or top[3] is None or not quote.event_ns <= quote.receive_ns
                or not Decimal(top[0]).is_finite() or not Decimal(top[3]).is_finite()
                or not 0 < Decimal(top[0]) <= Decimal(top[3]) or top[1] <= 0 or top[4] <= 0):
            raise ValueError("two-sided quote required")
    if (option_quote.instrument_id != definition.instrument_id
            or option_quote.raw_symbol != definition.raw_symbol
            or underlying_quote.instrument_id != definition.underlying_id
            or underlying_quote.raw_symbol != definition.underlying_contract
            or not option_quote.namespace.startswith("COMEX:OG:")
            or not underlying_quote.namespace.startswith("COMEX:GC:")
            or option_quote.publisher_id != underlying_quote.publisher_id
            or abs(option_quote.receive_ns-underlying_quote.receive_ns) > maximum_skew_ns):
        raise ValueError("option/underlying identity or synchronization mismatch")
    if open_interest is not None:
        if (not isinstance(open_interest,OpenInterest)
                or (open_interest.publisher_id,open_interest.instrument_id) !=
                   (option_quote.publisher_id,definition.instrument_id)
                or open_interest.available_ns > cutoff_ns):
            raise ValueError("OI identity or point-in-time availability mismatch")
    data = {"schema":"gc-options-research-input-v1","definition":asdict(definition),
            "definition_available_ns":definition_available_ns,"option_quote":asdict(option_quote),
            "underlying_quote":asdict(underlying_quote),"quote_available_ns":quote_available_ns,
            "cutoff_ns":cutoff_ns,"open_interest":asdict(open_interest) if open_interest else None,
            "model_outputs":None,"gamma_flip":None,"dealer_positioning":None,
            "american_greeks_certified":False,"gil_enabled":False,"trading_eligible":False,
            "limitation":"OI is published aggregate contracts, not signed dealer inventory. Complete chains and reviewed model assumptions are required."}
    # Preserve definition datetime presentation alongside native observation ns.
    from monatise.application.persistence import _json_value
    data = _json_value(data)
    return {**data,"input_sha256":canonical_hash(data)}

"""Observed dataset capabilities and metadata-only instrument discovery.

Dataset is feed origin, schema is record shape, raw symbol is contract identity.
No static list grants an entitlement or opens a market-data connection.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from monatise.adapters.databento_identity import timestamp_ns
from monatise.research.databento.acquisition import canonical_hash

EXTENSION_DATASETS = frozenset({"XNAS.ITCH", "XNYS.PILLAR", "OPRA.PILLAR",
                               "XCBF.PITCH", "XEUR.EOBI", "IFUS.IMPACT"})
CME_SCHEMAS = frozenset({"definition", "statistics", "status", "ohlcv-1m", "ohlcv-1h",
                        "trades", "mbp-1", "mbp-10", "mbo"})
PRODUCTS = {"GC": ("XCEC", "COMEX", "GC.FUT"),
            "OG": ("XCEC", "COMEX", "OG.OPT"),
            "ES": ("XCME", "CME", "ES.FUT"),
            "NQ": ("XCME", "CME", "NQ.FUT"),
            "CL": ("XNYM", "NYMEX", "CL.FUT")}


@dataclass(frozen=True)
class DatasetCapability:
    dataset: str
    schemas: tuple[str, ...]
    observed_at_ns: int
    source_sha256: str
    entitlement_reference: str | None = None

    def __post_init__(self):
        timestamp_ns(self.observed_at_ns)
        if self.dataset != "GLBX.MDP3":
            raise ValueError("only CME integration implemented; extensions need their own review")
        if (not isinstance(self.schemas, tuple) or not self.schemas
                or len(self.schemas) > 64 or len(set(self.schemas)) != len(self.schemas)
                or any(not isinstance(s, str) or not s or len(s) > 32 for s in self.schemas)
                or not re.fullmatch(r"[a-f0-9]{64}", self.source_sha256)):
            raise ValueError("bounded observed schemas and metadata hash required")

    def require(self, schema, *, at_ns, licensed=False):
        timestamp_ns(at_ns)
        if at_ns < self.observed_at_ns or schema not in self.schemas or schema not in CME_SCHEMAS:
            raise ValueError("schema unavailable or not implemented for this dataset")
        if licensed and not self.entitlement_reference:
            raise ValueError("schema listing does not establish account entitlement")


@dataclass(frozen=True)
class InstrumentMetadata:
    dataset: str
    publisher_id: int
    instrument_id: int
    raw_symbol: str
    product: str
    exchange: str
    kind: str
    event_ns: int
    receive_ns: int
    expiration_ns: int
    maturity_year: int
    maturity_month: int
    strike_fixed: int | None
    underlying_id: int | None
    native_terms: tuple[tuple[str, str], ...]
    definition_sha256: str

    def __post_init__(self):
        for t in (self.event_ns,self.receive_ns,self.expiration_ns):timestamp_ns(t)
        if (self.dataset != "GLBX.MDP3" or self.product not in PRODUCTS
                or self.exchange != PRODUCTS[self.product][0]
                or type(self.publisher_id) is not int or not 0 < self.publisher_id < 65536
                or type(self.instrument_id) is not int or not 0 < self.instrument_id < 2**32
                or not self.event_ns <= self.receive_ns < self.expiration_ns
                or not re.fullmatch(r"[a-f0-9]{64}",self.definition_sha256)
                or not isinstance(self.native_terms,tuple)):
            raise ValueError("validated immutable CME metadata required")
        if (any(not isinstance(t,tuple) or len(t)!=2 or any(not isinstance(v,str) for v in t) for t in self.native_terms)
                or len(dict(self.native_terms)) != len(self.native_terms)
                or not {"currency","min_price_increment"} <= dict(self.native_terms).keys()
                or dict(self.native_terms)["currency"] != "USD"):
            raise ValueError("native currency and tick metadata required")
        try:
            tick=int(dict(self.native_terms)["min_price_increment"])
        except ValueError:
            raise ValueError("native tick metadata invalid") from None
        if not 0 < tick < 2**63-1:
            raise ValueError("native tick metadata invalid")
        if self.product == "OG":
            if (self.kind not in {"C","P"} or not re.fullmatch(r"OG[A-Za-z0-9 .+-]{1,60}",self.raw_symbol)
                    or type(self.strike_fixed) is not int or not 0 < self.strike_fixed < 2**63-1
                    or type(self.underlying_id) is not int or not 0 < self.underlying_id < 2**32):
                raise ValueError("exact standard OG metadata required")
        else:
            match=re.fullmatch(r"(GC|ES|NQ|CL)([FGHJKMNQUVXZ])(\d{1,2})",self.raw_symbol)
            if (self.kind != "F" or match is None or match[1] != self.product
                    or type(self.maturity_year) is not int or not 1900 <= self.maturity_year <= 2200
                    or self.maturity_month != "FGHJKMNQUVXZ".index(match[2])+1
                    or self.maturity_year % 10**len(match[3]) != int(match[3])
                    or self.strike_fixed is not None or self.underlying_id is not None):
                raise ValueError("exact futures maturity metadata required")

    @property
    def namespace(self):
        return f"{PRODUCTS[self.product][1]}:{self.product}:{self.raw_symbol}"


def discover(record, *, publishers, capability, as_of_ns):
    """Normalize definition identity only; economic/model conventions need review.

    Parent symbols are discovery hints only. Every acquisition uses exact raw
    identities. Deleted, spreads, expired and unavailable definitions are rejected.
    Original native bytes are hashed and should remain in the raw archive.
    """
    capability.require("definition", at_ns=as_of_ns)
    product, kind = str(record.asset), str(record.instrument_class)
    if product not in PRODUCTS:
        raise ValueError("product convention not reviewed")
    exchange = PRODUCTS[product][0]
    if (publishers.get(record.publisher_id) != (capability.dataset, "GLBX")
            or str(record.exchange) != exchange or record.leg_count != 0
            or str(record.user_defined_instrument) != "N"
            or str(record.security_update_action) not in {"A", "M"}
            or str(record.currency) != "USD"):
        raise ValueError("contradictory publisher or unsupported outright")
    event, receive, expiry = map(timestamp_ns, (record.ts_event, record.ts_recv, record.expiration))
    if not event <= receive <= as_of_ns < expiry:
        raise ValueError("definition expired or not available at cutoff")
    raw = str(record.raw_symbol)
    if type(record.instrument_id) is not int or not 0 < record.instrument_id < 2**32:
        raise ValueError("invalid instrument identity")
    if product == "OG":
        if (kind not in {"C", "P"} or str(record.security_type) != "OOF"
                or not re.fullmatch(r"OG[A-Za-z0-9 .+-]{1,60}", raw)
                or type(record.underlying_id) is not int or not 0 < record.underlying_id < 2**32
                or type(record.strike_price) is not int or not 0 < record.strike_price < 2**63-1):
            raise ValueError("invalid standard futures option metadata")
        strike, underlying = record.strike_price, record.underlying_id
    else:
        match = re.fullmatch(r"(GC|ES|NQ|CL)([FGHJKMNQUVXZ])(\d{1,2})", raw)
        if (kind != "F" or str(record.security_type) != "FUT" or match is None
                or match[1] != product or type(record.maturity_year) is not int
                or not 1900 <= record.maturity_year <= 2200
                or record.maturity_month != "FGHJKMNQUVXZ".index(match[2])+1
                or record.maturity_year % 10**len(match[3]) != int(match[3])):
            raise ValueError("raw contract and maturity mismatch")
        strike = underlying = None
    terms = tuple((name, str(getattr(record, name))) for name in
                  ("currency", "unit_of_measure", "unit_of_measure_qty", "display_factor",
                   "min_price_increment", "min_price_increment_amount"))
    import hashlib
    return InstrumentMetadata(capability.dataset, record.publisher_id, record.instrument_id,
        raw, product, exchange, kind, event, receive, expiry, record.maturity_year,
        record.maturity_month, strike, underlying, terms, hashlib.sha256(bytes(record)).hexdigest())


def select_contracts(definitions, *, product, at_ns):
    """Explicit deterministic candidates, never automatic most-active rolling."""
    timestamp_ns(at_ns)
    if product not in PRODUCTS:
        raise ValueError("product not reviewed")
    eligible = [d for d in definitions if d.product == product and d.receive_ns <= at_ns < d.expiration_ns]
    identities = [(d.publisher_id, d.instrument_id) for d in eligible]
    if len(identities) != len(set(identities)):
        raise ValueError("resolve definition revisions before selecting contracts")
    return tuple(sorted(eligible, key=lambda d: (d.expiration_ns, d.raw_symbol, d.instrument_id)))


class DatasetRegistry:
    def __init__(self):
        self._observations = {}

    def observe(self, capability):
        if not isinstance(capability, DatasetCapability):
            raise ValueError("observed capability required")
        previous = self._observations.get(capability.dataset)
        if previous and capability.observed_at_ns <= previous.observed_at_ns:
            raise ValueError("metadata observations must advance")
        self._observations[capability.dataset] = capability

    def get(self, dataset):
        if dataset not in self._observations:
            raise ValueError("dataset availability has not been observed")
        return self._observations[dataset]

    @property
    def sha256(self):
        return canonical_hash({k: asdict(v) for k, v in sorted(self._observations.items())})

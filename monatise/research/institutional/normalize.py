"""Existing native normalizers wrapped with explicit terms and source positions."""
from dataclasses import dataclass
from decimal import Decimal
import hashlib

from monatise.research.databento.datasets import discover
from monatise.research.databento.advanced import AdvancedAdapters
from monatise.research.databento.candles import normalize_candle
from monatise.research.databento.options import normalize_open_interest
from .models import Contract, MarketObservation, Source, number

# Descriptors do not grant availability, exact identities, conventions or activation.
SECONDARY = {p: {"enabled": False, "definition_required": True} for p in ("CL", "YM", "RTY", "BTC", "ETH")}


@dataclass(frozen=True)
class EconomicConvention:
    product: str
    tick_size: Decimal
    multiplier: Decimal
    price_unit: str
    reference: str

    def __post_init__(self):
        if self.product not in {"GC", "ES", "NQ", "CL", "OG"} or not self.price_unit or not self.reference:
            raise ValueError("reviewed_product_convention_required")
        number(self.tick_size, positive=True)
        number(self.multiplier, positive=True)


def definition(record, *, capability, publishers, as_of_ns, convention):
    import databento_dbn as dbn
    if not isinstance(record, dbn.InstrumentDefMsg) or not isinstance(convention, EconomicConvention):
        raise ValueError("native_definition_and_explicit_convention_required")
    metadata = discover(record, publishers=publishers, capability=capability, as_of_ns=as_of_ns)
    if metadata.product != convention.product:
        raise ValueError("economic_convention_product_mismatch")
    return Contract(metadata, "futures_option" if metadata.kind in {"C", "P"} else "futures",
        "USD", convention.tick_size, convention.multiplier, convention.price_unit, convention.reference)


def observation(record, *, schema, contract, archive_sha256, ordinal,
                retrieval_ns, admission_ns, evidence_kind, enabled_schemas=()):
    """No client, environment lookup, implicit live feed or acquisition."""
    import databento_dbn as dbn
    if schema not in enabled_schemas:
        raise ValueError("institutional_schema_disabled")
    source = Source(archive_sha256, hashlib.sha256(bytes(record)).hexdigest(), ordinal,
                    retrieval_ns, admission_ns, evidence_kind)
    if (record.publisher_id, record.instrument_id) != contract.identity[1:3]:
        raise ValueError("native_contract_identity_mismatch")
    flags = int(getattr(record, "flags", 0))
    sequence = getattr(record, "sequence", None)
    event, receive = record.ts_event, getattr(record, "ts_recv", None)
    if schema == 'definition':
        if not isinstance(record,dbn.InstrumentDefMsg) or source.record_sha256 != contract.metadata.definition_sha256:
            raise ValueError('exact_normalized_definition_required')
        payload=(contract.metadata.raw_symbol,contract.metadata.kind,str(contract.tick_size),str(contract.multiplier))
    elif schema in {"trades", "mbp-1", "mbp-10"}:
        value = AdvancedAdapters(identity=contract.metadata, enabled_schemas=(schema,)).normalize(schema, record)
        payload = value.payload
    elif schema in {"ohlcv-1m", "ohlcv-1h"}:
        value = normalize_candle(record, schema=schema, identity=contract.metadata,
            retrieval_ns=retrieval_ns, evidence_kind="AUTHENTIC_HISTORICAL_DOWNLOAD"
            if evidence_kind == "AUTHENTIC_ARCHIVED_RECORD" else evidence_kind)
        payload = (value.open_ns, value.close_ns, *value.prices_fixed, value.volume)
    elif schema == "statistics":
        value = normalize_open_interest(record, available_ns=admission_ns)
        payload = ("OPEN_INTEREST", value.contracts, value.reference_ns, value.published_ns,
                   int(record.stat_flags), int(record.update_action))
    elif schema == "status":
        if not isinstance(record, dbn.StatusMsg):
            raise ValueError("native_status_required")
        payload = (str(record.is_trading), str(record.is_quoting), int(record.action), int(record.reason))
    else:
        raise ValueError("schema_not_implemented")
    return MarketObservation(contract, schema, event, receive, source, payload, flags, sequence)

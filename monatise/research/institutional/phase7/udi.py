"""Explicit research admission of CME dynamically listed outright OG strikes.

Keep tag 9779=Y and original bytes/hash. Never rewrite the record to N or relax
the shared standard-only normalizer. UDI is distinct from multi-leg UDS.
"""
from dataclasses import dataclass
from decimal import Decimal
import hashlib,re

from monatise.research.databento.datasets import InstrumentMetadata
from ..models import Contract
from ..normalize import definition,EconomicConvention

UDI_SPEC='https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457703567/User%2BDefined%2BInstruments%2B-%2BUDI'
OG_SPEC='https://www.cmegroup.com/rulebook/COMEX/1a/115.pdf'


@dataclass(frozen=True)
class UDIReview:
    definition_sha256: str
    review_reference: str
    mechanism_specification: str=UDI_SPEC
    exercise_settlement_specification: str=OG_SPEC


def reviewed_definition(record, *, underlying,capability,publishers,as_of_ns,review=None):
    import databento_dbn as dbn
    if not isinstance(record,dbn.InstrumentDefMsg):raise ValueError('original_native_definition_required')
    if (str(record.unit_of_measure)!='TRYOZ' or int(record.unit_of_measure_qty)!=100*10**9
            or int(record.display_factor)!=10000000 or int(record.min_price_increment)!=100000000
            or str(record.currency)!='USD' or str(record.strike_price_currency)!='USD'):
        raise ValueError('native_OG_economics_must_match_reviewed_convention')
    convention=EconomicConvention('OG',Decimal('.1'),Decimal(100),'USD_per_troy_oz',OG_SPEC)
    if str(record.user_defined_instrument)=='N':
        return definition(record,capability=capability,publishers=publishers,as_of_ns=as_of_ns,convention=convention)
    original=hashlib.sha256(bytes(record)).hexdigest()
    capability.require('definition',at_ns=as_of_ns)
    match=re.fullmatch(r'OG([FGHJKMNQUVXZ])(\d{1,2}) ([CP])(\d+(?:\.\d+)?)',str(record.raw_symbol))
    if (not isinstance(review,UDIReview) or review.definition_sha256!=original or not review.review_reference
            or review.mechanism_specification!=UDI_SPEC or review.exercise_settlement_specification!=OG_SPEC
            or not isinstance(underlying,Contract) or underlying.metadata.product!='GC' or underlying.asset_class!='futures'
            or str(record.user_defined_instrument)!='Y' or str(record.asset)!='OG'
            or str(record.instrument_class) not in {'C','P'} or record.leg_count!=0
            or str(record.security_type)!='OOF' or str(record.secsubtype) not in {'',' '} or match is None
            or str(record.exchange)!='XCEC' or publishers.get(record.publisher_id)!=('GLBX.MDP3','GLBX')
            or record.publisher_id!=underlying.metadata.publisher_id or record.underlying_id!=underlying.metadata.instrument_id
            or str(record.underlying)!=underlying.metadata.raw_symbol
            or str(record.currency)!='USD' or str(record.strike_price_currency)!='USD'
            or str(record.unit_of_measure)!='TRYOZ' or int(record.unit_of_measure_qty)!=100*10**9
            or int(record.display_factor)!=10000000 or int(record.min_price_increment)!=100000000
            or str(record.security_update_action) not in {'A','M'}
            or not int(record.ts_event)<=int(record.ts_recv)<=as_of_ns<int(record.expiration)<=underlying.metadata.expiration_ns
            or str(record.cfi)[2:3]!='A'):
        raise ValueError('reviewed_exact_OG_UDI_outright_required')
    month='FGHJKMNQUVXZ'.index(match[1])+1
    if (record.maturity_month!=month or record.maturity_year%10**len(match[2])!=int(match[2])
            or underlying.metadata.maturity_year!=record.maturity_year
            or underlying.metadata.maturity_month!=month+(month%2)
            or match[3]!=str(record.instrument_class) or Decimal(match[4])*10**9!=record.strike_price):
        raise ValueError('UDI_symbol_strike_or_underlying_month_mismatch')
    terms=tuple((name,str(getattr(record,name))) for name in ('currency','unit_of_measure','unit_of_measure_qty',
        'display_factor','min_price_increment','min_price_increment_amount','user_defined_instrument','leg_count','cfi'))
    metadata=InstrumentMetadata('GLBX.MDP3',record.publisher_id,record.instrument_id,str(record.raw_symbol),
        'OG','XCEC',str(record.instrument_class),int(record.ts_event),int(record.ts_recv),int(record.expiration),
        record.maturity_year,record.maturity_month,int(record.strike_price),record.underlying_id,terms,original)
    return Contract(metadata,'futures_option','USD',Decimal('.1'),Decimal(100),'USD_per_troy_oz',
        review.review_reference+':CME_UDI_OUTRIGHT_ORIGINAL_FLAG_Y')

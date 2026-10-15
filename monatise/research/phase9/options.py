"""Independent quote pricing and publication-cycle OI; production GIL stays disabled."""
import hashlib

from monatise.research.databento.advanced import AdvancedAdapters
from monatise.research.institutional.models import digest, encode, number
from monatise.research.institutional.phase7.greeks import GreekInput, validated
from monatise.research.institutional.phase8.eligibility import quote_eligibility, pair_eligibility, oi_eligibility
from . import SAFETY


def option_inputs(*, option, underlying, option_quote, future_quote, option_available_ns,
                  future_available_ns, market_cutoff_ns, local_cutoff_ns,
                  rate, rate_as_of_ns, rate_source_sha256, convention_reference,
                  style, evidence_kind, oi_record=None, oi_available_ns=None,
                  oi_captured=False, oi_entitled=None):
    """Raw native quote validators are reused. No price/quote/OI imputation.

    Model inputs bind exact native options to their defined underlying. Pricing
    and OI eligibility are evaluated independently; OI never enters the IV solve.
    Exposure is unsigned per-leg sensitivity, never dealer GEX or a gamma wall.
    """
    if (option.asset_class!='futures_option' or underlying.asset_class!='futures'
            or underlying.metadata.product!='GC' or option.metadata.underlying_id!=underlying.metadata.instrument_id
            or option.metadata.dataset!=underlying.metadata.dataset or option.metadata.kind not in {'C','P'}
            or not 0 < market_cutoff_ns < min(option.metadata.expiration_ns,underlying.metadata.expiration_ns)
            or evidence_kind not in {'AUTHENTIC_ARCHIVED_RECORD','AUTHENTIC_LIVE_CAPTURE','ENGINEERING_SYNTHETIC'}):
        raise ValueError('exact_GC_option_underlying_and_causal_cutoff_required')
    components = {}
    quotes = []
    for name,contract,row,available in (
        ('option_quote',option,option_quote,option_available_ns),
        ('future_quote',underlying,future_quote,future_available_ns)):
        try:
            if row is not None:
                AdvancedAdapters(identity=contract.metadata,enabled_schemas=('mbp-1',)).normalize('mbp-1',row)
            q = quote_eligibility(row,identity=contract.identity[1:3],market_cutoff_ns=market_cutoff_ns,
                available_ns=available,local_cutoff_ns=local_cutoff_ns)
        except (ValueError,TypeError,AttributeError,ArithmeticError) as exc:
            q = dict(eligible=False,status='INVALID',reasons=[type(exc).__name__])
        quotes.append(q);components[name] = q
    pair = pair_eligibility(*quotes)
    oi = oi_eligibility(oi_record,identity=option.identity[1:3],available_ns=oi_available_ns or local_cutoff_ns,
        local_cutoff_ns=local_cutoff_ns,market_cutoff_ns=market_cutoff_ns,captured=oi_captured,entitled=oi_entitled)
    greeks = dict(status='UNAVAILABLE',iv=None,delta=None,gamma=None,vega=None,theta=None,
                  rejection_reasons=pair['reasons'])
    if pair['eligible']:
        q,f = quotes
        x = GreekInput(future=float((number(f['bid'])+number(f['ask']))/2),
            strike=float(option.metadata.strike_fixed/10**9),years=(option.metadata.expiration_ns-market_cutoff_ns)/(365*86400*10**9),
            rate=rate,kind=option.metadata.kind,style=style,bid=float(q['bid']),ask=float(q['ask']),
            cutoff_ns=market_cutoff_ns,rate_as_of_ns=rate_as_of_ns,rate_source_sha256=rate_source_sha256,
            convention_reference=convention_reference,
            evidence_kind='AUTHENTIC_ARCHIVED_RECORD' if evidence_kind=='AUTHENTIC_LIVE_CAPTURE' else evidence_kind,
            native_instrument_id=option.metadata.instrument_id)
        greeks = validated(x)
    exposure = None
    if greeks['status']=='VALIDATED_MODEL_SENSITIVITIES' and oi['status'] in {'PUBLISHED_ZERO','PUBLISHED_NONZERO'}:
        exposure = str(number(greeks['gamma'])*oi['value']*option.multiplier)
    result = dict(availability='PARTIAL_ANALYSIS' if greeks.get('iv') is not None else 'UNAVAILABLE',
        contract=option.identity,underlying=underlying.identity,quotes=components,pair=pair,
        pricing_and_model_greeks=greeks,open_interest=oi,unsigned_gamma_times_OI_multiplier=exposure,
        exposure_unit='OPTION_PREMIUM_USD_PER_FUTURES_USD_SQUARED',
        signed_dealer_GEX=None,gamma_flip=None,options_derived_levels=None,
        production_GIL_status='DISABLED_PROVIDER_HIERARCHY_UNCHANGED',decision='NO_TRADE',
        qualification_status='NOT_EVALUATED',evidence_kind=evidence_kind,
        quote_source_sha256=[hashlib.sha256(bytes(q)).hexdigest() if q is not None else None
                             for q in (option_quote,future_quote)],**SAFETY)
    result['reproducibility_sha256'] = digest(result)
    return encode(result)

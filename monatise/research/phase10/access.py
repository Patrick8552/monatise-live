"""Native futures request boundary around existing pure engines; no acquisition."""
from dataclasses import dataclass
from monatise.research.institutional.models import digest,encode
from monatise.research.databento.candles import WIDTHS
from . import SAFETY

FEATURES={'trade_features','mbp-1','mbp-10','open_interest','oi_change',*(f'price:{tf}' for tf in WIDTHS)}

@dataclass(frozen=True)
class AnalysisRequest:
    symbols: tuple[str,...]
    cutoff_ns: int
    timeframes: tuple[str,...]=('1m','5m','15m','1h','4h')
    mandatory: tuple[str,...]=('price:1m',)

    def __post_init__(self):
        if (not isinstance(self.symbols,tuple) or not 1<=len(self.symbols)<=3 or len(set(self.symbols))!=len(self.symbols)
            or any(not isinstance(s,str) or not 1<=len(s)<=32 for s in self.symbols)
            or type(self.cutoff_ns) is not int or self.cutoff_ns<=0
            or not isinstance(self.timeframes,tuple) or not 1<=len(self.timeframes)<=len(WIDTHS)
            or len(set(self.timeframes))!=len(self.timeframes) or any(t not in WIDTHS for t in self.timeframes)
            or not isinstance(self.mandatory,tuple) or not self.mandatory or len(self.mandatory)>len(FEATURES)
            or any(k not in FEATURES for k in self.mandatory)):
            raise ValueError('bounded_native_analysis_request_required')

class AnalysisService:
    def __init__(self,pipeline,*,source_health=None):
        self.pipeline=pipeline
        self.source_health=source_health or (lambda now:dict(status='OFFLINE_CONTEXT_ONLY',live_verified=False))

    def analyse(self,request):
        if not isinstance(request,AnalysisRequest):raise ValueError('typed_analysis_request_required')
        known={g.contract.metadata.raw_symbol:i for i,g in self.pipeline.gates.items()}
        health=self.source_health(request.cutoff_ns);outputs={}
        for symbol in request.symbols:
            if symbol not in known:
                outputs[symbol]=dict(availability='UNAVAILABLE',reason='exact_contract_not_loaded',decision='NO_TRADE',qualification_status='NOT_EVALUATED',**SAFETY);continue
            iid=known[symbol]
            try:
                result=self.pipeline.analyse(iid,now_ns=request.cutoff_ns,mandatory=request.mandatory,
                    requested=tuple(dict.fromkeys([*(f'price:{t}' for t in request.timeframes),'trade_features','mbp-1','mbp-10','oi_change'])))
                # Retain useful historical calculations, but never present them
                # as live-ready after a source interruption or stale checkpoint.
                result['calculated_availability']=result['availability']
                result['calculated_reproducibility_sha256']=result['reproducibility_sha256']
                if health.get('quarantined') or health.get('stale_checkpoint'):
                    result['availability']='UNAVAILABLE'
                for tf in request.timeframes:
                    result['components'].setdefault('price:'+tf,dict(available=False,reason='insufficient_validated_history'))
                result.update(capture_health=health,live_analysis_certified=False,analysis_access='READ_ONLY',
                    decision='NO_TRADE',qualification_status='NOT_EVALUATED',**SAFETY)
                from .diagnostics import second_intervals
                result['seconds_bar_diagnostics']=second_intervals(self.pipeline.gates[iid],
                    cutoff_ns=request.cutoff_ns,watermark_ns=health.get('interval_watermarks',{}).get('ohlcv-1s'),
                    source_unreliable=bool(health.get('quarantined') or health.get('stale_checkpoint')))
                result['participant_identity']='UNAVAILABLE_ANONYMOUS_EXCHANGE_DATA'
                result['order_flow_depth_status']='NOT_CAPTURED_OR_NOT_VALIDATED'
                result['reproducibility_sha256']=digest({k:v for k,v in result.items() if k!='reproducibility_sha256'})
                outputs[symbol]=result
            except Exception as exc:
                outputs[symbol]=dict(availability='UNAVAILABLE',reason=str(exc) if isinstance(exc,(ValueError,TypeError,ArithmeticError)) else 'unexpected_analytical_component_failure',error_type=type(exc).__name__,unexpected_error=not isinstance(exc,(ValueError,TypeError,ArithmeticError)),decision='NO_TRADE',qualification_status='NOT_EVALUATED',**SAFETY)
        result=dict(version='phase10-read-only-analysis-v1',request=encode(request),instruments=outputs,
            basis_status='NOT_APPLICABLE_NATIVE_FUTURES',options_required=False,
            decision='NO_TRADE',qualification_status='NOT_EVALUATED',**SAFETY)
        result['reproducibility_sha256']=digest(result)
        return result

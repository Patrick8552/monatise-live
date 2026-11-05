"""BTC source readiness, separating available data from research assumptions."""
from . import CODE_HASH, BASE_COMMIT
from .models import current_quote,encode,MINUTE
from .evidence import build_frames,bias
from .diagnostics import executed_window


def btc_readiness(archive,policy,cutoff):
    if archive.instrument.product!='BTC':
        raise ValueError('BTC_ONLY_READINESS_SCOPE')
    snapshot=archive.snapshot(cutoff)
    frames=build_frames(snapshot,policy)
    q=current_quote(snapshot)
    quote_ok=q is not None and not q.quality and not q.source.startswith('MODELED_SPREAD_FROM_NATIVE_CLOSE:')
    quote_fresh=bool(quote_ok and policy.quote_age_ns is not None and 0<=cutoff-q.receive_ns<=policy.quote_age_ns)
    return encode({'schema':'btc-native-data-readiness-v1','base_commit':BASE_COMMIT,'code_hash':CODE_HASH,
        'instrument':snapshot.instrument,'cutoff_ns':cutoff,'manifest_hash':archive.manifest_hash,
        'replay_mode':archive.mode,'bar_source_mode':archive.report.get('bar_source_mode','VENDOR_OHLCV'),
        'policy_hash':policy.hash,'unresolved_policy_fields':policy.missing,
        'market_bias':bias(frames),
        'context':{tf:{'state':frame.state,'confirmed_pivots':len(frame.pivots),'reasons':frame.reasons}
                   for tf,frame in frames.items()},
        'native_l1':{'available':quote_ok,'fresh_under_registered_policy':quote_fresh,
            'spread_ticks':(q.ask-q.bid)/snapshot.instrument.tick if quote_ok else None,
            'provider_age_ns':cutoff-q.receive_ns if q else None,
            'quote_invalidations':len(snapshot.quote_invalidations),
            'synthetic_spread_enabled':archive.quote_model_ticks is not None},
        'executions':{str(m)+'m':executed_window(snapshot,m) for m in (5,15,60)},
        'trade_aggregation':archive.report.get('trade_aggregation'),
        'news':{'coverage_complete':snapshot.news_coverage,'required_by_policy':policy.news_required,
            'known_windows':len(snapshot.news),'data_vendor_is_not_economic_news_coverage':True},
        'source_report':archive.report,'account_risk_validation':'UNAVAILABLE_REFERENCE_ONLY_NO_ACCOUNT_SIZING',
        'strategy_validation':'NOT_ESTABLISHED_BY_DATA_READINESS','mode':'SHADOW',
        'execution_eligible':False,'orders_created':0})

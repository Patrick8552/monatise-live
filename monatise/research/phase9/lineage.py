"""Native OHLCV lineage validation; no analytical engines or qualification."""
from collections import defaultdict
from decimal import Decimal


def verify_bar_lineage(gate, bars, *, reviewed_history=False):
    """Reconcile OHLCV/volume against admitted canonical sources, including ties."""
    by_hash=defaultdict(list)
    for value in gate.lineage_observations():by_hash[value.source.record_sha256].append(value)
    for bar in bars:
        used=defaultdict(int);sources=[]
        for sha in bar.source_hashes:
            candidates=by_hash.get(sha,())
            index=used[sha]
            if index>=len(candidates):raise ValueError('bar_source_multiplicity_not_admitted')
            value=candidates[index];used[sha]+=1;sources.append(value)
        if (not sources or any(v.contract.metadata!=bar.identity for v in sources)
                or any(v.source.retrieval_ns>bar.retrieval_ns for v in sources)
                or len({v.source.evidence_kind for v in sources})!=1 and not
                (reviewed_history and {v.source.evidence_kind for v in sources}<=
                 {'AUTHENTIC_ARCHIVED_RECORD','AUTHENTIC_LIVE_CAPTURE'})):
            raise ValueError('bar_lineage_identity_availability_or_category_mismatch')
        categories={v.source.evidence_kind for v in sources}
        category=('MIXED_AUTHENTIC_HISTORY_AND_LIVE' if len(categories)>1 else
                  'AUTHENTIC_HISTORICAL_DOWNLOAD' if categories=={'AUTHENTIC_ARCHIVED_RECORD'} else next(iter(categories)))
        if bar.evidence_kind!=category:
            raise ValueError('bar_evidence_category_mismatch')
        schemas={v.schema for v in sources}
        sources.sort(key=lambda v:(v.event_ns,v.receive_ns or v.event_ns,v.source.ordinal))
        if schemas=={'trades'}:
            if any(not bar.open_ns<=v.event_ns<bar.close_ns for v in sources):raise ValueError('trade_bar_window_mismatch')
            prices=[int(Decimal(v.payload[0])*10**9) for v in sources]
            expected=(prices[0],max(prices),min(prices),prices[-1]);volume=sum(v.payload[1] for v in sources)
        elif len(schemas)==1 and next(iter(schemas)).startswith('ohlcv-'):
            if (any(not bar.open_ns<=v.payload[0]<v.payload[1]<=bar.close_ns for v in sources)
                    or any(a.payload[1]!=b.payload[0] for a,b in zip(sources,sources[1:]))
                    or sources[0].payload[0]!=bar.open_ns or sources[-1].payload[1]!=bar.close_ns):
                raise ValueError('native_bar_coverage_lineage_mismatch')
            expected=(sources[0].payload[2],max(v.payload[3] for v in sources),
                min(v.payload[4] for v in sources),sources[-1].payload[5]);volume=sum(v.payload[6] for v in sources)
        else:raise ValueError('mixed_or_nonprice_bar_sources')
        if bar.prices_fixed!=expected or bar.volume!=volume:raise ValueError('bar_price_or_volume_lineage_mismatch')


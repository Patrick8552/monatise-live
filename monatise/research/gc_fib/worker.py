"""Legacy archive-row conversion only; selector/qualification code deleted."""
from datetime import UTC,datetime
from monatise.application.hierarchy.coordinator import TimeframeSnapshot
from monatise.application.hierarchy.models import BoundaryStatus,NormalizedCandle,Provenance
from monatise.research.gc_fib.candles import GCBar,GCIdentity
from monatise.research.native_futures.retired import retired

def instant(ns):
    # Analysis bars are exactly second-aligned. Original ns remain in provenance.
    return datetime.fromtimestamp(ns // 10**9, UTC)


def parse_bar(value):
    data = dict(value)
    data["identity"] = GCIdentity(**data["identity"])
    data["source_hashes"] = tuple(data["source_hashes"])
    return GCBar(**data)


def snapshot(rows, *, timeframe, cutoff):
    prefix = tuple(b for b in rows if b.timeframe == timeframe and b.assumed_available_ns <= cutoff)[-200:]
    if not prefix: return None
    provenance = Provenance("databento-retrospective-gc", "XCEC", "GCZ6",
                            "native-ohlcv-1m", "gc-research-utc-grid-v1")
    normalized = tuple(NormalizedCandle(b.sha256,"GCZ6",timeframe,instant(b.open_ns),instant(b.close_ns),
        instant(b.open_ns),instant(b.assumed_available_ns),float(b.open),float(b.high),float(b.low),
        float(b.close),float(b.volume),True,BoundaryStatus.FINALIZED,b.sha256,provenance) for b in prefix)
    # Explicitly retrospective finalization assumption; never claim two local observations.
    return TimeframeSnapshot("GCZ6",timeframe,instant(cutoff),normalized,normalized[-1])


assess=retired
main=retired

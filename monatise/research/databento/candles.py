"""Contract-preserving historical bars and explicit exchange-calendar evidence.

UTC buckets are deterministic. Closed exchanges, missing/no-trade intervals and
forming bars remain distinct. No back-adjustment, spot conversion or gap filling.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from monatise.adapters.databento_identity import timestamp_ns
from monatise.research.databento.acquisition import canonical_hash, json_document
from monatise.research.databento.datasets import InstrumentMetadata

WIDTHS = {"1s":10**9,"5s":5*10**9,"1m":60*10**9,"5m":300*10**9,"15m":900*10**9,
          "1h":3600*10**9,"4h":14400*10**9}


@dataclass(frozen=True)
class ExchangeCalendar:
    dataset: str
    exchange: str
    source_reference: str
    source_sha256: str
    version: str
    valid_from_ns: int
    valid_to_ns: int
    intervals: tuple[tuple[int,int], ...]

    def __post_init__(self):
        timestamp_ns(self.valid_from_ns); timestamp_ns(self.valid_to_ns)
        if (self.dataset != "GLBX.MDP3" or self.exchange not in {"XCEC","XCME","XNYM"}
                or not self.source_reference or not self.version
                or not re.fullmatch(r"[a-f0-9]{64}", self.source_sha256)
                or self.valid_from_ns >= self.valid_to_ns or not isinstance(self.intervals, tuple)
                or not self.intervals or len(self.intervals) > 10000):
            raise ValueError("reviewed bounded exchange-calendar evidence required")
        previous = self.valid_from_ns
        for interval in self.intervals:
            if not isinstance(interval, tuple) or len(interval) != 2:
                raise ValueError("immutable calendar intervals required")
            start,end = interval
            timestamp_ns(start); timestamp_ns(end)
            if not previous <= start < end <= self.valid_to_ns or start % WIDTHS["1m"] or end % WIDTHS["1m"]:
                raise ValueError("ordered nonoverlapping minute-aligned exchange sessions required")
            previous = end

    @property
    def sha256(self):
        return canonical_hash(asdict(self))

    def contains(self, start, end):
        if not self.valid_from_ns <= start < end <= self.valid_to_ns:
            raise ValueError("calendar coverage unavailable")
        return any(a <= start < end <= b for a,b in self.intervals)


@dataclass(frozen=True)
class HistoricalBar:
    identity: InstrumentMetadata
    timeframe: str
    open_ns: int
    close_ns: int
    prices_fixed: tuple[int,int,int,int]
    volume: int
    retrieval_ns: int
    source_hashes: tuple[str, ...]
    schema: str
    evidence_kind: str
    clock_review: object | None = None

    def __post_init__(self):
        if not isinstance(self.identity, InstrumentMetadata) or self.identity.kind != "F":
            raise ValueError("exact futures identity required")
        for t in (self.open_ns,self.close_ns,self.retrieval_ns): timestamp_ns(t)
        width = WIDTHS.get(self.timeframe)
        if not width or self.open_ns % width or self.close_ns != self.open_ns+width:
            raise ValueError("UTC-aligned fixed-duration bar required")
        upper=0
        if self.clock_review is not None:
            from .live_models import ClockReview
            if not isinstance(self.clock_review,ClockReview):raise ValueError('reviewed_bar_capture_clock_required')
            _,upper=self.clock_review.bounds(self.retrieval_ns)
        if not self.identity.event_ns <= self.open_ns < self.close_ns <= min(self.retrieval_ns+upper,self.identity.expiration_ns):
            raise ValueError("forming or expired-contract candle")
        if (not isinstance(self.prices_fixed, tuple) or len(self.prices_fixed) != 4
                or any(type(p) is not int or not -(2**63) < p < 2**63-1 for p in self.prices_fixed)
                or (self.identity.product != "CL" and min(self.prices_fixed) <= 0)):
            raise ValueError("invalid fixed-point prices")
        o,h,l,c = self.prices_fixed
        tick=int(dict(self.identity.native_terms)["min_price_increment"])
        if any(p % tick for p in self.prices_fixed):
            raise ValueError("OHLCV prices off contract tick")
        if not l <= min(o,c) <= max(o,c) <= h or type(self.volume) is not int or not 0 <= self.volume < 2**64-1:
            raise ValueError("invalid OHLCV geometry or volume")
        if (not isinstance(self.source_hashes,tuple) or not self.source_hashes
                or any(not re.fullmatch(r"[a-f0-9]{64}", h) for h in self.source_hashes)
                or self.schema not in {"ohlcv-1s","ohlcv-1m","ohlcv-1h","derived-ohlcv-v1"}
                or self.evidence_kind not in {"AUTHENTIC_HISTORICAL_DOWNLOAD","AUTHENTIC_LIVE_CAPTURE","ENGINEERING_SYNTHETIC"}):
            raise ValueError("explicit source provenance required")

    @property
    def sha256(self):
        return canonical_hash(asdict(self))


def normalize_candle(record, *, schema, identity, retrieval_ns, evidence_kind, clock_review=None):
    import databento_dbn as dbn
    expected = {"ohlcv-1s":("1s",dbn.RType.OHLCV_1S),"ohlcv-1m":("1m",dbn.RType.OHLCV_1M),"ohlcv-1h":("1h",dbn.RType.OHLCV_1H)}
    if schema not in expected:
        raise ValueError("historical candle schema unsupported")
    tf,rtype = expected[schema]
    if (not isinstance(record, dbn.OHLCVMsg) or record.rtype != rtype
            or (record.publisher_id,record.instrument_id) != (identity.publisher_id,identity.instrument_id)):
        raise ValueError("native OHLCV schema/contract mismatch")
    return HistoricalBar(identity,tf,record.ts_event,record.ts_event+WIDTHS[tf],
        (record.open,record.high,record.low,record.close),record.volume,retrieval_ns,
        (hashlib.sha256(bytes(record)).hexdigest(),),schema,evidence_kind,clock_review)


def quality(bars, *, identity, timeframe, start_ns, end_ns, as_of_ns, calendar):
    bars = tuple(bars)
    for t in (start_ns,end_ns,as_of_ns): timestamp_ns(t)
    width = WIDTHS[timeframe]
    if (not 0 < end_ns-start_ns <= 1_000_000*width or len(bars)>1_000_000 or start_ns % width or end_ns % width
            or (identity.dataset,identity.exchange) != (calendar.dataset,calendar.exchange)):
        raise ValueError("aligned request and matching exchange calendar required")
    admitted,forming,seen = [],[],set()
    for bar in sorted(bars,key=lambda b:b.open_ns):
        if bar.identity != identity or bar.timeframe != timeframe or not start_ns <= bar.open_ns < end_ns:
            raise ValueError("mixed contract/timeframe or bar outside request")
        if bar.open_ns in seen:
            raise ValueError("duplicate or revised candle rejected")
        seen.add(bar.open_ns)
        if not calendar.contains(bar.open_ns,bar.close_ns):
            raise ValueError("bar outside exchange trading interval")
        if bar.close_ns+10*10**9 > as_of_ns:
            forming.append(bar.open_ns)
        else:
            admitted.append(bar)
    expected = [t for t in range(start_ns,end_ns,width)
                if t+width+10*10**9 <= as_of_ns and calendar.contains(t,t+width)]
    missing = sorted(set(expected)-{b.open_ns for b in admitted})
    return tuple(admitted), {"calendar_sha256":calendar.sha256,"contract":identity.raw_symbol,
        "source_hashes":sorted({h for b in bars for h in b.source_hashes}),
        "missing_or_no_trade_intervals":missing,"forming_or_not_finalized":forming,
        "continuity_certified":False,"gap_fill_count":0,"trading_eligible":False}


def aggregate(bars, *, target, calendar):
    rows = tuple(sorted(bars,key=lambda b:b.open_ns))
    if not rows or len(rows)>1_000_000 or target not in WIDTHS or target == "1m":
        raise ValueError("bounded minute input and larger target timeframe required")
    identity,category = rows[0].identity,rows[0].evidence_kind
    if (identity.dataset,identity.exchange) != (calendar.dataset,calendar.exchange):
        raise ValueError("calendar identity mismatch")
    by_time = {}
    for bar in rows:
        if bar.identity != identity or bar.evidence_kind != category or bar.timeframe != "1m":
            raise ValueError("roll boundaries and evidence categories must be processed separately")
        if bar.open_ns in by_time:
            raise ValueError("duplicate candle rejected")
        if not calendar.contains(bar.open_ns,bar.close_ns):
            raise ValueError("minute outside exchange session")
        by_time[bar.open_ns] = bar
    width = WIDTHS[target]
    starts = sorted({b.open_ns//width*width for b in rows})
    output,rejected = [],[]
    for start in starts:
        end = start+width
        if not calendar.contains(start,end):
            rejected.append({"open_ns":start,"reason":"PARTIAL_SESSION_BOUNDARY"});continue
        missing = [t for t in range(start,end,WIDTHS["1m"]) if t not in by_time]
        if missing:
            rejected.append({"open_ns":start,"reason":"MISSING_OR_NO_TRADES_UNCERTIFIED","missing_ns":missing});continue
        children = [by_time[t] for t in range(start,end,WIDTHS["1m"])]
        output.append(HistoricalBar(identity,target,start,end,
            (children[0].prices_fixed[0],max(c.prices_fixed[1] for c in children),
             min(c.prices_fixed[2] for c in children),children[-1].prices_fixed[3]),
            sum(c.volume for c in children),max(c.retrieval_ns for c in children),
            tuple(h for c in children for h in c.source_hashes),"derived-ohlcv-v1",category,max(children,key=lambda c:c.retrieval_ns).clock_review))
    return tuple(output),tuple(rejected)


class ResearchArtifactStore:
    """Immutable normalized/derived/quality/replay objects; raw DBN stays separate."""
    KINDS = {"normalized", "candles", "indicators", "quality", "replays", "metadata", "costs"}

    def __init__(self, root):
        self.root = Path(root).resolve()

    def publish(self, kind, value):
        if kind not in self.KINDS:
            raise ValueError("unknown research layer")
        import json
        content = json.dumps(json_document(value),sort_keys=True,separators=(",",":"),allow_nan=False).encode()
        digest = hashlib.sha256(content).hexdigest()
        folder = self.root/kind;folder.mkdir(parents=True,exist_ok=True)
        path = folder/(digest+".json")
        import tempfile
        from monatise.research.databento.archive import _fsync_directory
        fd,staging = tempfile.mkstemp(prefix=".artifact-",dir=folder)
        try:
            with os.fdopen(fd,"wb") as out:
                out.write(content);out.flush();os.fsync(out.fileno())
            os.chmod(staging,0o400)
            try:
                os.link(staging,path)
            except FileExistsError:
                if path.is_symlink() or path.read_bytes() != content:
                    raise ValueError("immutable artifact integrity conflict")
            _fsync_directory(folder)
        finally:
            Path(staging).unlink()
            _fsync_directory(folder)
        return path,digest


@dataclass(frozen=True)
class RollSelection:
    old: InstrumentMetadata
    new: InstrumentMetadata
    effective_ns: int
    review_reference: str

    def __post_init__(self):
        timestamp_ns(self.effective_ns)
        if (self.old.raw_symbol == self.new.raw_symbol or self.old.product != self.new.product
                or self.old.dataset != self.new.dataset or not self.review_reference
                or not self.new.receive_ns <= self.effective_ns < self.new.expiration_ns):
            raise ValueError("explicit reviewed same-product roll with available new identity required")

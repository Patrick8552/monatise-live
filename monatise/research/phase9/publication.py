"""Durable local analytical candle outbox. No messages, orders or trade signals."""
import json
from pathlib import Path
import sqlite3

from monatise.research.databento.candles import WIDTHS
from monatise.research.institutional.models import digest, encode
from .candles import aggregate_complete
from .coordinator import verify_bar_lineage
from . import SAFETY


class CandlePublisher:
    def __init__(self, path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        if self.path.is_symlink():raise ValueError('regular_private_publication_store_required')
        self.db=sqlite3.connect(self.path);self.path.chmod(0o600)
        self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, key TEXT, kind TEXT, body TEXT, hash TEXT UNIQUE)')
        self.db.execute('CREATE TABLE IF NOT EXISTS active (key TEXT PRIMARY KEY, iid INTEGER, tf TEXT, opened INTEGER, closed INTEGER, hash TEXT, source_schemas TEXT, live INTEGER)')
        self.db.commit();self.highest={}
        for iid,tf,end in self.db.execute('SELECT iid,tf,MAX(closed) FROM active GROUP BY iid,tf'):self.highest[(iid,tf)]=end

    def _emit(self,key,kind,payload):
        body=dict(kind=kind,payload=encode(payload),**SAFETY);sha=digest(body)
        self.db.execute('INSERT OR IGNORE INTO events(key,kind,body,hash) VALUES (?,?,?,?)',
            (key,kind,json.dumps(body,sort_keys=True,separators=(',',':')),sha))
        return sha

    def retract_faults(self,pipeline):
        count=0
        with self.db:
            for iid,g in pipeline.gates.items():
                for schema,reason in g.faults.items():
                    event=g.fault_event_ns.get(schema,0)
                    rows=list(self.db.execute('SELECT key,hash,source_schemas FROM active WHERE iid=? AND live=1 AND closed>?',(iid,event)))
                    for key,sha,schemas in rows:
                        if schema not in json.loads(schemas):continue
                        self._emit(key,'CANDLE_RETRACTED',dict(prior_publication_sha256=sha,reason=reason,fault_event_ns=event))
                        self.db.execute('UPDATE active SET live=0 WHERE key=?',(key,));count+=1
        return count

    def advance(self,pipeline, *, now_ns, replay_ready, source_reference, interval_watermarks=None):
        if not source_reference:raise ValueError('native_transport_provenance_required')
        retracted=self.retract_faults(pipeline);published=0;rejected=[]
        pending_highest=dict(self.highest)
        with self.db:
            for iid,g in pipeline.gates.items():
                # Retain native history for incomplete parent buckets, but only
                # rebuild targets after their last durable publication. A live
                # second tick must not re-aggregate the entire session.
                native={};schemas={};frames={}
                for tf,rows in pipeline.bars[iid].items():
                    schema='ohlcv-'+tf
                    if (schema,iid) not in replay_ready:continue
                    allowed=[b for b in rows.values() if b.close_ns+10*10**9<=now_ns and b.retrieval_ns<=now_ns
                        and (interval_watermarks is None or b.close_ns<=interval_watermarks.get(schema,0))
                        and (schema not in g.faults or b.close_ns<=g.fault_event_ns.get(schema,0))]
                    if allowed:native[tf]=tuple(sorted(allowed,key=lambda b:b.open_ns))
                for tf in tuple(dict.fromkeys((*native,'5s','1m','5m','15m','1h','4h'))):
                    last=pending_highest.get((iid,tf),0)
                    if tf in native:
                        frames[tf]=tuple(b for b in native[tf] if b.close_ns>last);schemas[tf]=('ohlcv-'+tf,)
                        continue
                    candidates=[src for src in native if WIDTHS[src]<WIDTHS[tf] and WIDTHS[tf]%WIDTHS[src]==0]
                    if not candidates:continue
                    source=max(candidates,key=lambda src:WIDTHS[src])
                    children=tuple(b for b in native[source] if b.open_ns>=last)
                    if not children:continue
                    bars,errors=aggregate_complete(children,target=tf,calendar=pipeline.calendars[iid])
                    rejected.extend(dict(iid=iid,timeframe=tf,**e) for e in errors[-8:])
                    if bars:frames[tf]=bars;schemas[tf]=('ohlcv-'+source,)
                candidates=tuple(bar for bars in frames.values() for bar in bars)
                if candidates:verify_bar_lineage(g,candidates)
                for tf,bars in frames.items():
                    for bar in bars:
                        key=digest([g.contract.identity,tf,bar.open_ns])
                        sha=self._emit(key,'CANDLE_FINAL',dict(bar=bar,available_ns=now_ns,source_reference=source_reference,
                            coverage='VALIDATED_NATIVE_BAR_OR_ALL_NATIVE_CHILDREN',price_clock='PROVIDER_OHLCV_RECEIVE_TIME_BUCKET',
                            complete_exchange_continuity=False,source_schemas=schemas[tf],frozen_H1_parent_qualified=False))
                        self.db.execute('INSERT OR IGNORE INTO active VALUES (?,?,?,?,?,?,?,1)',
                            (key,iid,tf,bar.open_ns,bar.close_ns,sha,json.dumps(schemas[tf])))
                        pending_highest[(iid,tf)]=max(pending_highest.get((iid,tf),0),bar.close_ns);published+=1
        self.highest=pending_highest
        return dict(published=published,retracted=retracted,aggregation_rejections=rejected,**SAFETY)

    def summary(self):
        return dict(event_counts=dict(self.db.execute('SELECT kind,COUNT(*) FROM events GROUP BY kind')),
            active_candles=self.db.execute('SELECT COUNT(*) FROM active WHERE live=1').fetchone()[0],
            by_timeframe=dict(self.db.execute('SELECT tf,COUNT(*) FROM active WHERE live=1 GROUP BY tf')),
            local_analytical_outbox_only=True,**SAFETY)

    def close(self):self.db.execute('PRAGMA wal_checkpoint(TRUNCATE)');self.db.close()

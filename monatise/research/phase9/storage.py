"""Bounded SQLite FULL/WAL native BLOB journal and durable recovery checkpoints.

Bytes are committed before normalization/checkpoint advancement. Restart rebuilds
analytical state from the verified native BLOBs, never from trusted mutable JSON.
Keep this database private: it contains licensed raw market data.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from monatise.adapters.databento_identity import timestamp_ns
from monatise.research.institutional.models import digest, encode


class DurableSpool:
    def __init__(self, path, *, maximum_records=1000000, maximum_bytes=1024**3):
        if (type(maximum_records) is not int or not 1<=maximum_records<=1000000
                or type(maximum_bytes) is not int or not 1024<=maximum_bytes<=1024**3):
            raise ValueError('bounded_durable_spool_required')
        self.path = Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        if self.path.is_symlink(): raise ValueError('private_regular_database_required')
        fd = os.open(self.path,os.O_CREAT|os.O_RDWR,0o600); os.close(fd)
        self.path.chmod(0o600)
        self.db = sqlite3.connect(self.path)
        self.db.execute('PRAGMA journal_mode=WAL'); self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS raw (id INTEGER PRIMARY KEY, delivery TEXT UNIQUE, schema TEXT, captured INTEGER, native BLOB, hash TEXT, kind TEXT, admitted INTEGER, metadata_hash TEXT, rejection TEXT, clock_review TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS states (name TEXT PRIMARY KEY, value TEXT, hash TEXT)')
        self.db.commit()
        self.maximum_records,self.maximum_bytes = maximum_records,maximum_bytes
        self.count,self.bytes = self.db.execute('SELECT COUNT(*), COALESCE(SUM(length(native)),0) FROM raw').fetchone()
        if self.count>maximum_records or self.bytes>maximum_bytes: raise ValueError('existing_spool_exceeds_bounds')

    def append(self, schema, record, *, capture_ns, delivery_id, evidence_kind, admitted=True, rejection_reason=None, clock_review=None):
        timestamp_ns(capture_ns)
        if (not isinstance(delivery_id,str) or not 0<len(delivery_id)<=256 or type(admitted) is not bool or
                evidence_kind not in {'AUTHENTIC_LIVE_CAPTURE','AUTHENTIC_ARCHIVED_RECORD','ENGINEERING_SYNTHETIC'}):
            raise ValueError('bounded_delivery_identity_and_evidence_required')
        if rejection_reason is not None and (admitted or not isinstance(rejection_reason,str) or len(rejection_reason)>128):raise ValueError('bounded_rejection_reason_required')
        if clock_review is not None:clock_review.bounds(capture_ns)
        review_text=json.dumps(encode(clock_review),sort_keys=True)
        raw=bytes(record);sha=hashlib.sha256(raw).hexdigest()
        metadata_hash=digest([delivery_id,schema,capture_ns,sha,evidence_kind,admitted,rejection_reason,review_text])
        old=self.db.execute('SELECT id,schema,captured,hash,kind,admitted,metadata_hash,rejection,clock_review FROM raw WHERE delivery=?',(delivery_id,)).fetchone()
        if old:
            if old[1:]!=(schema,capture_ns,sha,evidence_kind,admitted,metadata_hash,rejection_reason,review_text): raise ValueError('durable_delivery_revision')
            return old[0],sha,False
        if not 1<=len(raw)<=65536 or self.count>=self.maximum_records or self.bytes+len(raw)>self.maximum_bytes:
            raise ValueError('durable_spool_capacity_exceeded')
        # A row stores the original native record, addressed by its own SHA256.
        with self.db:
            cursor=self.db.execute('INSERT INTO raw(delivery,schema,captured,native,hash,kind,admitted,metadata_hash,rejection,clock_review) VALUES (?,?,?,?,?,?,?,?,?,?)',
                (delivery_id,schema,capture_ns,raw,sha,evidence_kind,admitted,metadata_hash,rejection_reason,review_text))
        self.count+=1;self.bytes+=len(raw)
        return cursor.lastrowid,sha,True

    def checkpoint(self, name, value):
        text=json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
        if not name or len(name)>128 or len(text)>4*1024**2: raise ValueError('bounded_checkpoint_required')
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO states VALUES (?,?,?)',(name,text,digest(value)))

    def load(self, name):
        row=self.db.execute('SELECT value,hash FROM states WHERE name=?',(name,)).fetchone()
        if row is None:return None
        value=json.loads(row[0])
        if digest(value)!=row[1]: raise ValueError('checkpoint_integrity_failure')
        return value

    def replay(self, pipeline, *, ordinal_offset=0):
        import databento_dbn as dbn
        outcomes=[]
        for ordinal,delivery,schema,stamp,raw,sha,kind,admitted,metadata_hash,rejection,review_text in self.db.execute('SELECT id,delivery,schema,captured,native,hash,kind,admitted,metadata_hash,rejection,clock_review FROM raw ORDER BY id'):
            if digest([delivery,schema,stamp,sha,kind,bool(admitted),rejection,review_text])!=metadata_hash:raise ValueError('durable_metadata_hash_mismatch')
            if hashlib.sha256(raw).hexdigest()!=sha:raise ValueError('durable_native_hash_mismatch')
            rows=dbn.DBNDecoder(has_metadata=False,input_version=3).write_and_decode(raw)
            if len(rows)!=1 or bytes(rows[0])!=raw:raise ValueError('native_decoder_roundtrip_failure')
            record=rows[0]
            if rejection:
                gate=pipeline.gates.get(getattr(record,'instrument_id',None))
                if gate is not None:gate.transport_gap(schema,rejection,event_ns=getattr(record,'ts_event',None))
            if not admitted:continue
            if isinstance(record,(dbn.SystemMsg,dbn.SymbolMappingMsg,dbn.ErrorMsg)):continue
            from monatise.research.databento.live_models import ClockReview
            review=json.loads(review_text)
            review=ClockReview(**review) if review else None
            outcomes.append(pipeline.ingest(record,schema=schema,archive_sha256=sha,ordinal=ordinal+ordinal_offset,
                capture_ns=stamp,admission_ns=stamp,evidence_kind=kind,clock_review=review))
        return outcomes

    def close(self):
        self.db.execute('PRAGMA wal_checkpoint(TRUNCATE)');self.db.close()

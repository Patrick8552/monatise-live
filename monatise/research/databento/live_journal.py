"""Private framed native-record journal; immutable only after verified sealing.

This format preserves original DBN record bytes, not a standalone DBN archive.
Connection schema, source/capture clocks and native ordinals are explicit.
Unsealed or interrupted files remain quarantined; they are never admitted by EOF.
"""
import hashlib
import json
import os
from pathlib import Path
import struct
import time

from monatise.adapters.databento_identity import timestamp_ns
from monatise.research.institutional.models import encode
from .live_models import SAFETY

MAGIC=b'MONATISE-NATIVE-LIVE-JOURNAL\x01'
FRAME=struct.Struct('>QI')
MAGIC_V2=b'MONATISE-NATIVE-LIVE-JOURNAL\x02'
FRAME_V2=struct.Struct('>QQI')


class NativeJournal:
    def __init__(self,root, *, schema,scope,evidence_kind='AUTHENTIC_LIVE_CAPTURE',arrival_order=False):
        if schema not in scope.schemas or evidence_kind not in {'AUTHENTIC_LIVE_CAPTURE','ENGINEERING_SYNTHETIC'}:
            raise ValueError('reviewed_live_journal_schema_required')
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=False);self.root.chmod(0o700)
        self.schema,self.scope,self.kind=schema,scope,evidence_kind
        self.path=self.root/'records.partial';self.file=self.path.open('xb');self.path.chmod(0o600)
        self.arrival_order=arrival_order;self.last_arrival=0;self.first_arrival=0;self.wall_regressions=0
        self.frame=FRAME_V2 if arrival_order else FRAME
        self.magic=MAGIC_V2 if arrival_order else MAGIC
        self.file.write(self.magic);self.file.flush();os.fsync(self.file.fileno())
        self.count=0;self.bytes=len(self.magic);self.last_capture=0;self.closed=False

    def append(self,record, *, capture_ns,arrival_ns=None):
        timestamp_ns(capture_ns)
        native=bytes(record)
        if self.arrival_order and (type(arrival_ns) is not int or arrival_ns<=0 or arrival_ns<self.last_arrival):
            raise ValueError('native_monotonic_arrival_order_required')
        if (self.closed or (not self.arrival_order and capture_ns<self.last_capture) or not 1<=len(native)<=65536
                or self.count>=self.scope.maximum_records
                or self.bytes+self.frame.size+len(native)>self.scope.maximum_bytes):
            raise ValueError('live_journal_limit_or_clock_failure')
        if self.arrival_order and not self.count:self.first_arrival=arrival_ns
        ordinal=self.count
        begun=time.perf_counter_ns()
        self.file.write(self.frame.pack(capture_ns,arrival_ns,len(native)) if self.arrival_order else self.frame.pack(capture_ns,len(native)));self.file.write(native)
        written=time.perf_counter_ns()
        # Cursor advancement occurs only after durable source bytes.
        self.file.flush();os.fsync(self.file.fileno())
        self.last_append_timings=dict(journal_write=written-begun,journal_synchronization=time.perf_counter_ns()-written)
        self.wall_regressions+=int(bool(self.count) and capture_ns<self.last_capture)
        self.count+=1;self.bytes+=self.frame.size+len(native);self.last_capture=capture_ns
        if self.arrival_order:self.last_arrival=arrival_ns
        return ordinal,hashlib.sha256(native).hexdigest()

    def close(self, *, quality,checkpoint):
        if self.closed:raise ValueError('live_journal_already_sealed')
        self.file.flush();os.fsync(self.file.fileno());self.file.close();self.closed=True
        with self.path.open('rb') as source:raw_hash=hashlib.file_digest(source,'sha256').hexdigest()
        manifest=dict(version='native-live-journal-v2' if self.arrival_order else 'native-live-journal-v1',schema=self.schema,scope_sha256=self.scope.sha256,
            raw_sha256=raw_hash,record_count=self.count,bytes=self.bytes,quality=quality,checkpoint=checkpoint,
            evidence_kind=self.kind,source_format='framed-original-DBN-record-bytes',local_capture_wall_regressions=self.wall_regressions,first_arrival_ns=self.first_arrival if self.arrival_order else None,last_arrival_ns=self.last_arrival if self.arrival_order else None,
            capture_clock_semantics='ORIGINAL_UTC_WALL_AND_MONOTONIC_ARRIVAL_V2' if self.arrival_order else 'LEGACY_UTC_WALL_ORDER',**SAFETY)
        target=self.root/('records.sealed' if not quality['quarantined'] else 'records.quarantined')
        os.replace(self.path,target);target.chmod(0o400)
        manifest['source_filename']=target.name
        p=self.root/'manifest.json';p.write_text(json.dumps(encode(manifest),sort_keys=True,indent=2));p.chmod(0o400)
        directory=os.open(self.root,os.O_RDONLY)
        try:os.fsync(directory)
        finally:os.close(directory)
        return manifest


def verify(root):
    root=Path(root);manifest=json.loads((root/'manifest.json').read_text())
    group=root.parent/'report.json'
    if group.exists() and json.loads(group.read_text())['quality']['quarantined']:
        raise ValueError('capture_group_quarantined')
    if manifest['quality']['quarantined']:raise ValueError('quarantined_live_journal_cannot_be_admitted')
    path=root/manifest['source_filename']
    with path.open('rb') as source:actual_hash=hashlib.file_digest(source,'sha256').hexdigest()
    if path.is_symlink() or path.name!='records.sealed' or actual_hash!=manifest['raw_sha256']:
        raise ValueError('native_live_journal_hash_mismatch')
    rows=[];previous=0
    with path.open('rb') as f:
        magic=f.read(len(MAGIC))
        if manifest['version'] not in {'native-live-journal-v1','native-live-journal-v2'}:raise ValueError('unknown_native_journal_version')
        v2=manifest['version']=='native-live-journal-v2'
        if magic!=(MAGIC_V2 if v2 else MAGIC):raise ValueError('native_live_journal_header_invalid')
        frame=FRAME_V2 if v2 else FRAME
        while chunk:=f.read(frame.size):
            if len(chunk)!=frame.size:raise ValueError('truncated_live_frame')
            if v2:stamp,arrival,size=frame.unpack(chunk)
            else:stamp,size=frame.unpack(chunk);arrival=stamp
            timestamp_ns(stamp)
            if arrival<previous or v2 and arrival<=0 or not 1<=size<=65536:raise ValueError('invalid_native_frame')
            value=f.read(size)
            if len(value)!=size:raise ValueError('truncated_native_record')
            if v2 and not rows and arrival!=manifest['first_arrival_ns']:raise ValueError('native_arrival_manifest_mismatch')
            rows.append((stamp,value));previous=arrival
    if v2 and previous!=manifest['last_arrival_ns']:raise ValueError('native_arrival_manifest_mismatch')
    if len(rows)!=manifest['record_count'] or path.stat().st_size!=manifest['bytes']:
        raise ValueError('live_journal_manifest_count_mismatch')
    return manifest,tuple(rows)

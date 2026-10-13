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

from monatise.adapters.databento_identity import timestamp_ns
from monatise.research.institutional.models import encode
from .live_models import SAFETY

MAGIC=b'MONATISE-NATIVE-LIVE-JOURNAL\x01'
FRAME=struct.Struct('>QI')


class NativeJournal:
    def __init__(self,root, *, schema,scope,evidence_kind='AUTHENTIC_LIVE_CAPTURE'):
        if schema not in scope.schemas or evidence_kind not in {'AUTHENTIC_LIVE_CAPTURE','ENGINEERING_SYNTHETIC'}:
            raise ValueError('reviewed_live_journal_schema_required')
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=False);self.root.chmod(0o700)
        self.schema,self.scope,self.kind=schema,scope,evidence_kind
        self.path=self.root/'records.partial';self.file=self.path.open('xb');self.path.chmod(0o600)
        self.file.write(MAGIC);self.file.flush();os.fsync(self.file.fileno())
        self.count=0;self.bytes=len(MAGIC);self.last_capture=0;self.closed=False

    def append(self,record, *, capture_ns):
        timestamp_ns(capture_ns)
        native=bytes(record)
        if (self.closed or capture_ns<self.last_capture or not 1<=len(native)<=65536
                or self.count>=self.scope.maximum_records
                or self.bytes+FRAME.size+len(native)>self.scope.maximum_bytes):
            raise ValueError('live_journal_limit_or_clock_failure')
        ordinal=self.count
        self.file.write(FRAME.pack(capture_ns,len(native)));self.file.write(native)
        # Cursor advancement occurs only after durable source bytes.
        self.file.flush();os.fsync(self.file.fileno())
        self.count+=1;self.bytes+=FRAME.size+len(native);self.last_capture=capture_ns
        return ordinal,hashlib.sha256(native).hexdigest()

    def close(self, *, quality,checkpoint):
        if self.closed:raise ValueError('live_journal_already_sealed')
        self.file.flush();os.fsync(self.file.fileno());self.file.close();self.closed=True
        with self.path.open('rb') as source:raw_hash=hashlib.file_digest(source,'sha256').hexdigest()
        manifest=dict(version='native-live-journal-v1',schema=self.schema,scope_sha256=self.scope.sha256,
            raw_sha256=raw_hash,record_count=self.count,bytes=self.bytes,quality=quality,checkpoint=checkpoint,
            evidence_kind=self.kind,source_format='framed-original-DBN-record-bytes',**SAFETY)
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
        if f.read(len(MAGIC))!=MAGIC:raise ValueError('native_live_journal_header_invalid')
        while chunk:=f.read(FRAME.size):
            if len(chunk)!=FRAME.size:raise ValueError('truncated_live_frame')
            stamp,size=FRAME.unpack(chunk);timestamp_ns(stamp)
            if stamp<previous or not 1<=size<=65536:raise ValueError('invalid_native_frame')
            value=f.read(size)
            if len(value)!=size:raise ValueError('truncated_native_record')
            rows.append((stamp,value));previous=stamp
    if len(rows)!=manifest['record_count'] or path.stat().st_size!=manifest['bytes']:
        raise ValueError('live_journal_manifest_count_mismatch')
    return manifest,tuple(rows)

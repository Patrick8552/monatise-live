"""Full-session private storage rotation, preserving global native positions.

Sealed segments are retained and hash checked. Resource ceilings stop acquisition;
no licensed archive is deleted to free capacity and no rotation reconnects a feed.
"""
from dataclasses import dataclass
import hashlib,json,os,sqlite3
from pathlib import Path

from monatise.research.databento.live_journal import NativeJournal, verify
from monatise.research.institutional.models import digest, encode
from .storage import DurableSpool


def file_hash(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def atomic_json(path,value):
    path=Path(path);temp=path.with_suffix('.pending')
    with temp.open('w') as f:
        json.dump(encode(value),f,sort_keys=True);f.flush();os.fsync(f.fileno())
    temp.chmod(0o600);os.replace(temp,path)
    fd=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)


@dataclass(frozen=True)
class RotationPolicy:
    records_per_segment:int=100000
    bytes_per_segment:int=32*1024**2
    seconds_per_segment:int=900
    maximum_segments:int=256
    maximum_total_bytes:int=16*1024**3

    def __post_init__(self):
        if (any(type(v) is not int or v<=0 for v in (self.records_per_segment,self.bytes_per_segment,
            self.seconds_per_segment,self.maximum_segments,self.maximum_total_bytes))
            or self.records_per_segment>1000000 or not 1024<=self.bytes_per_segment<=1024**3
            or self.seconds_per_segment>86400 or self.maximum_segments>4096
            or self.maximum_total_bytes<self.bytes_per_segment):raise ValueError('bounded_full_session_rotation_required')


class RotatingNativeJournal:
    def __init__(self,root, *, schema,scope,evidence_kind='AUTHENTIC_LIVE_CAPTURE',policy=None,checkpoint=None):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=False);self.root.chmod(0o700)
        self.schema,self.scope,self.kind=schema,scope,evidence_kind
        self.policy=policy or RotationPolicy();self.checkpoint=checkpoint or (lambda:{})
        self.segments=[];self.journal=None;self.count=0;self.bytes=0;self.first_capture=0;self.last_capture=0;self.closed=False

    def _seal(self,quality):
        if self.journal is None:return
        manifest=self.journal.close(quality=quality,checkpoint=self.checkpoint())
        self.segments.append(dict(path=self.journal.root.name,first_ordinal=self.count-self.journal.count,
            end_ordinal=self.count,manifest_sha256=file_hash(self.journal.root/'manifest.json'),manifest=manifest,
            previous_sha256=digest(self.segments[-1]) if self.segments else None))
        self.bytes+=self.journal.bytes;self.journal=None
        atomic_json(self.root/'rotation.json',dict(version='phase9-native-rotation-v1',schema=self.schema,
            scope_sha256=self.scope.sha256,segments=self.segments,record_count=self.count,closed=False))

    def append(self,record, *, capture_ns):
        raw=bytes(record);p=self.policy
        if self.closed:raise ValueError('closed_rotating_journal')
        if capture_ns<self.last_capture:raise ValueError('cross_segment_capture_clock_regression')
        if self.journal is not None and (self.journal.count>=min(p.records_per_segment,self.scope.maximum_records) or
                self.journal.bytes+12+len(raw)>min(p.bytes_per_segment,self.scope.maximum_bytes) or
                capture_ns-self.first_capture>=p.seconds_per_segment*10**9):
            self._seal(dict(quarantined=False,storage_integrity_only=True,analytical_freshness_certified=False))
        if self.bytes+(self.journal.bytes if self.journal else 0)+len(raw)+12>p.maximum_total_bytes:
            raise ValueError('full_session_native_storage_limit')
        if self.journal is None:
            if len(self.segments)>=p.maximum_segments:raise ValueError('full_session_segment_limit')
            self.journal=NativeJournal(self.root/f'segment-{len(self.segments):05d}',schema=self.schema,
                scope=self.scope,evidence_kind=self.kind);self.first_capture=capture_ns
        self.journal.append(record,capture_ns=capture_ns)
        ordinal=self.count;self.count+=1;self.last_capture=capture_ns
        return ordinal,hashlib.sha256(raw).hexdigest()

    def close(self, *, quality,checkpoint):
        if self.closed:raise ValueError('rotation_already_closed')
        self._seal(quality);self.closed=True
        value=dict(version='phase9-native-rotation-v1',schema=self.schema,scope_sha256=self.scope.sha256,
            segments=self.segments,record_count=self.count,bytes=self.bytes,quality=quality,checkpoint=checkpoint,
            closed=True,source_format='rotated-framed-original-DBN-record-bytes')
        atomic_json(self.root/'rotation.json',value);return value


def verify_rotated_native(root):
    root=Path(root);index=json.loads((root/'rotation.json').read_text());end=0;previous=None
    if not index['closed']:raise ValueError('unclosed_native_rotation')
    if index.get('quality',{}).get('quarantined'):raise ValueError('quarantined_native_rotation')
    for item in index['segments']:
        path=root/item['path']
        if (path.parent!=root or path.is_symlink() or item['first_ordinal']!=end
                or item['previous_sha256']!=previous or file_hash(path/'manifest.json')!=item['manifest_sha256']):
            raise ValueError('native_segment_chain_invalid')
        manifest,frames=verify(path)
        if len(frames)!=item['end_ordinal']-end:raise ValueError('native_segment_count_mismatch')
        end=item['end_ordinal'];previous=digest(item)
        for offset,(capture,raw) in enumerate(frames):yield item['first_ordinal']+offset,capture,raw
    if end!=index['record_count']:raise ValueError('native_rotation_count_mismatch')


class RotatingSpool:
    def __init__(self,root, *, policy=None):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.root.chmod(0o700)
        self.policy=policy or RotationPolicy()
        self.state=DurableSpool(self.root/'state.sqlite')
        self.state.db.execute('CREATE TABLE IF NOT EXISTS deliveries (delivery TEXT PRIMARY KEY, ordinal INTEGER, hash TEXT, signature TEXT)');self.state.db.commit()
        self.segments=self.state.load('segments') or []
        self.count=0;self.bytes=0;self.current=None;self.first_capture=None
        for item in self.segments:
            path=self.root/item['path']
            if path.parent!=self.root or path.is_symlink():raise ValueError('private_spool_segment_required')
            if item.get('sha256') and file_hash(path)!=item['sha256']:raise ValueError('sealed_spool_integrity_failure')
            with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as db:
                count,size=db.execute('SELECT COUNT(*),COALESCE(SUM(length(native)),0) FROM raw').fetchone()
            if item['base']!=self.count:raise ValueError('global_source_position_discontinuity')
            self.count+=count;self.bytes+=size
        if self.segments and not self.segments[-1].get('sha256'):
            self.current=DurableSpool(self.root/self.segments[-1]['path'],maximum_records=self.policy.records_per_segment,
                maximum_bytes=self.policy.bytes_per_segment)
            self.first_capture=self.current.db.execute('SELECT MIN(captured) FROM raw').fetchone()[0]
        self.sealed_bytes=self.bytes-(self.current.bytes if self.current else 0)

    def _save(self):self.state.checkpoint('segments',self.segments)

    def _seal(self):
        if self.current is None:return
        self.current.close();self.segments[-1]['sha256']=file_hash(self.current.path)
        self.sealed_bytes+=self.current.bytes;self.current.path.chmod(0o400);self.current=None;self.first_capture=None;self._save()

    def append(self,schema,record, **kwargs):
        p=self.policy;size=len(bytes(record))
        signature=digest(dict(schema=schema,record_sha256=hashlib.sha256(bytes(record)).hexdigest(),arguments=kwargs))
        prior=self.state.db.execute('SELECT ordinal,hash,signature FROM deliveries WHERE delivery=?',(kwargs['delivery_id'],)).fetchone()
        if prior:
            if prior[2]!=signature:raise ValueError('durable_delivery_revision')
            return prior[0],prior[1],False
        if self.bytes+size>p.maximum_total_bytes:raise ValueError('full_session_spool_limit')
        if self.current and (self.current.count>=p.records_per_segment or self.current.bytes+size>p.bytes_per_segment or
                self.first_capture is not None and kwargs['capture_ns']-self.first_capture>=p.seconds_per_segment*10**9):self._seal()
        if self.current is None:
            if len(self.segments)>=p.maximum_segments:raise ValueError('full_session_spool_segment_limit')
            name=f'raw-{len(self.segments):05d}.sqlite'
            self.current=DurableSpool(self.root/name,maximum_records=p.records_per_segment,maximum_bytes=p.bytes_per_segment)
            self.segments.append(dict(path=name,base=self.count,sha256=None));self._save()
        local,sha,added=self.current.append(schema,record,**kwargs)
        if self.first_capture is None:self.first_capture=kwargs['capture_ns']
        if added:self.count+=1;self.bytes+=size
        global_ordinal=self.segments[-1]['base']+local
        with self.state.db:self.state.db.execute('INSERT INTO deliveries VALUES (?,?,?,?)',(kwargs['delivery_id'],global_ordinal,sha,signature))
        return global_ordinal,sha,added

    def checkpoint(self,name,value):self.state.checkpoint(name,value)
    def load(self,name):return self.state.load(name)

    def replay(self,pipeline):
        outcomes=[]
        for item in self.segments:
            path=self.root/item['path']
            if item.get('sha256') and file_hash(path)!=item['sha256']:raise ValueError('sealed_spool_integrity_failure')
            view=object.__new__(DurableSpool);view.db=sqlite3.connect(f'file:{path}?mode=ro',uri=True)
            try:outcomes.extend(view.replay(pipeline,ordinal_offset=item['base']))
            finally:view.db.close()
        return outcomes

    def close(self):self._seal();self.state.close()

"""Persistent, append-only native manifests; validated merges never fill missing bars."""
from pathlib import Path
import json,sqlite3
from hashlib import sha256
from monatise.research.unified.archive import load_archive
from monatise.research.unified.models import canonical,digest,encode
from . import require_btc

class HistoryStore:
    def __init__(self,path):
        self.db=sqlite3.connect(path);self.db.execute('PRAGMA foreign_keys=ON');self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''CREATE TABLE IF NOT EXISTS archives(hash TEXT PRIMARY KEY,body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS bars(contract TEXT,opened INTEGER,payload TEXT NOT NULL,PRIMARY KEY(contract,opened));
        CREATE TABLE IF NOT EXISTS lineage(contract TEXT,opened INTEGER,archive TEXT REFERENCES archives(hash),PRIMARY KEY(contract,opened,archive));
        CREATE TABLE IF NOT EXISTS coverage(archive TEXT,body TEXT,PRIMARY KEY(archive,body));''')
    def close(self):self.db.close()
    def admit(self,manifest):
        a=load_archive(manifest);s=a.snapshot(json.loads(Path(manifest).read_text())['as_of_ns']);require_btc(s)
        # Every input hash/native byte/control is verified by the original archive reader.
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO archives VALUES(?,?)',(a.manifest_hash,canonical({'path':str(Path(manifest).resolve()),'manifest_sha256':sha256(Path(manifest).read_bytes()).hexdigest()})))
            for b in a.bars:
                economic=canonical({'close_ns':b.close_ns,'open':b.open,'high':b.high,'low':b.low,'close':b.close,'volume':b.volume})
                old=self.db.execute('SELECT payload FROM bars WHERE contract=? AND opened=?',(b.contract,b.open_ns)).fetchone()
                if old and old[0]!=economic:raise ValueError('HISTORICAL_REVISION_REQUIRES_EXPLICIT_REVIEW')
                self.db.execute('INSERT OR IGNORE INTO bars VALUES(?,?,?)',(b.contract,b.open_ns,economic))
                self.db.execute('INSERT OR IGNORE INTO lineage VALUES(?,?,?)',(b.contract,b.open_ns,a.manifest_hash))
            for c in a.coverage:self.db.execute('INSERT OR IGNORE INTO coverage VALUES(?,?)',(a.manifest_hash,canonical(c)))
        return {'contract':a.instrument.key,'manifest_hash':a.manifest_hash,'bar_count':len(a.bars),'persisted_unique_bars':self.db.execute('SELECT count(*) FROM bars WHERE contract=?',(a.instrument.key,)).fetchone()[0],'synthetic_bars':0}

def merge_manifests(paths,output):
    if not paths:raise ValueError('MANIFESTS_REQUIRED')
    inputs=[json.loads(Path(p).read_text()) for p in paths]
    for p,m in zip(paths,inputs):
        a=load_archive(p)
        if a.instrument.product!='BTC':raise ValueError('BTC_NATIVE_FUTURES_ONLY')
    base=max(inputs,key=lambda m:m['as_of_ns']).copy()
    keys=[(load_archive(p).instrument.key,m['mode'],m.get('bar_source_mode','VENDOR_OHLCV')) for p,m in zip(paths,inputs)]
    if len(set(keys))!=1:raise ValueError('EXACT_CONTRACT_AND_CLOCK_MODE_REQUIRED')
    for field,key in [('history','sha256'),('captures','receipt_sha256')]:
        base[field]=list({r[key]:r for m in inputs for r in m.get(field,[])}.values())
    # Longest dated calendar must contain every requested coverage window; do not union unknown schedules.
    if any(m['calendar']['intervals']!=base['calendar']['intervals'] for m in inputs):
        raise ValueError('EXPLICIT_COMMON_DATED_CALENDAR_REVIEW_REQUIRED')
    target=Path(output)
    if target.exists():raise ValueError('IMMUTABLE_MERGED_MANIFEST_TARGET_REQUIRED')
    target.write_text(json.dumps(base,indent=2)+'\n')
    try:load_archive(target)
    except BaseException:target.unlink();raise
    return target

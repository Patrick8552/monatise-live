"""BTC-only, opt-in native futures research. No broker or provider connections."""
from pathlib import Path
from hashlib import sha256
VERSION = 'btc-native-upgrade-v1'
def code_hash():
    h=sha256()
    for p in sorted(Path(__file__).parent.glob('*.py')):
        h.update(p.name.encode()+b'\0'+p.read_bytes()+b'\0')
    from monatise.research.unified import CODE_HASH
    h.update(CODE_HASH.encode())
    return h.hexdigest()
def require_btc(snapshot):
    i=snapshot.instrument
    if i.product!='BTC' or i.dataset!='GLBX.MDP3' or i.venue!='XCME':
        raise ValueError('BTC_NATIVE_FUTURES_ONLY')

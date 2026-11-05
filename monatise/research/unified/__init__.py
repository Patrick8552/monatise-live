"""Opt-in native-futures research decisions. No production registration or execution."""
VERSION = 'unified-native-shadow-v1'
BASE_COMMIT = '1979440d8c25dda5d2b7d7c3a92ba5ede1a008d7'


def _source_hash():
    from pathlib import Path
    from hashlib import sha256
    root = Path(__file__).resolve().parent
    h = sha256()
    for path in sorted(root.glob('*.py')):
        h.update(path.name.encode()+b'\0'+path.read_bytes()+b'\0')
    return h.hexdigest()


# Captured on package import: a stream cannot reuse decisions from changed code.
CODE_HASH = _source_hash()

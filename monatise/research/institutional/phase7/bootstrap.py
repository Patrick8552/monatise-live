"""Launch worker under -I with explicit repository root; no credential env."""
import json
from pathlib import Path
import sys

sys.path.insert(0,sys.argv[1])
from monatise.research.institutional.phase7.replay import replay
from monatise.research.institutional.models import encode

request=json.loads(Path(sys.argv[2]).read_text())
output=Path(sys.argv[3])
with output.open('x') as f:
    f.write(json.dumps(encode(replay(request)),sort_keys=True,indent=2,allow_nan=False))
output.chmod(0o600)

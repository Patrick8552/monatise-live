"""Credential-free -I scanner; no network, provider client or production writes."""
from pathlib import Path
import json
import sys
import zoneinfo

if __name__ == "__main__":
    source,repository,data_root,phase3a_root,destination = map(Path,sys.argv[1:])
    sys.dont_write_bytecode = True
    sys.path.insert(0,str(repository))
    from monatise.research.gold_retrospective.runner import verify_research_checkout
    verify_research_checkout(source)
    from monatise.research.gc_qualification.isolation import install_guard
    install_guard(read_roots=(source,repository,data_root,phase3a_root,Path(sys.prefix),Path(sys.base_prefix),
        Path(sys.executable).resolve().parents[1],destination.parent,*zoneinfo.TZPATH),output=destination)
    from monatise.research.gc_continuity.forensics import scan
    result = scan(data_root,phase3a_root=phase3a_root,repository=repository)
    with destination.open("x") as out:json.dump(result,out,sort_keys=True,separators=(",",":"),allow_nan=False)
    destination.chmod(0o400)

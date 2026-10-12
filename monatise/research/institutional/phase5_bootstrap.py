"""Phase 5 uses the existing research guard and a credential-free subprocess."""
from pathlib import Path
import asyncio
import sys
import zoneinfo

if __name__=='__main__':
    repository,input_file,output_file=map(Path,sys.argv[1:])
    sys.dont_write_bytecode=True
    sys.path.insert(0,str(repository))
    loop=asyncio.new_event_loop()
    import json
    request=json.loads(input_file.read_text())
    from monatise.research.institutional.isolation import install_guard
    roots=(repository,input_file,Path(sys.prefix),Path(sys.base_prefix),
           Path(sys.executable).resolve().parents[1],output_file.parent,*zoneinfo.TZPATH)
    if request.get('data_root'):roots+=(Path(request['data_root']),Path(request['prepared_file']),)
    if request.get('esnq_root'):roots+=(Path(request['esnq_root']),)
    install_guard(read_roots=roots,output=output_file)
    try:
        from monatise.research.institutional.phase5_worker import main
        main(request,output_file,repository=repository,loop=loop)
    finally:
        loop.run_until_complete(loop.shutdown_default_executor());loop.close()

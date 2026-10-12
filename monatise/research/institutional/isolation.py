"""Trusted-worker defense in depth; no assertion of a hostile-code OS sandbox."""
from pathlib import Path
from importlib.abc import MetaPathFinder
import os
import sys

from monatise.research.gc_qualification.isolation import install_guard as base_guard

BLOCKED_IMPORTS=('monatise.live','monatise.application.deployment','monatise.application.production',
    'monatise.application.ftmo_master','monatise.application.ftmo_execution',
    'monatise.application.telegram_analysis','monatise.application.trade_publication')


def install_guard(*,read_roots,output):
    base_guard(read_roots=read_roots,output=output)
    def guard(event,args):
        if event=='import' and any(args[0]==name or args[0].startswith(name+'.') for name in BLOCKED_IMPORTS):
            raise PermissionError('institutional_execution_or_publisher_import_forbidden')
        if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
            path=Path(os.fsdecode(args[0]))
            if (set(path.parts)&{'.aws','.ssh','.codex','credentials','secrets'}
                    or path.suffix in {'.pem','.key'} or path.name in {'credentials.json','secrets.json'}):
                raise PermissionError('institutional_secret_read_forbidden')
    sys.addaudithook(guard)
    class BlockExecutionImports(MetaPathFinder):
        def find_spec(self,fullname,path=None,target=None):
            if any(fullname==name or fullname.startswith(name+'.') for name in BLOCKED_IMPORTS):
                raise PermissionError('institutional_execution_or_publisher_import_forbidden')
            return None
    sys.meta_path.insert(0,BlockExecutionImports())

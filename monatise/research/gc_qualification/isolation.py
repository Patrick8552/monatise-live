"""Defense in depth for this trusted offline worker; not an OS security sandbox."""
import os
from pathlib import Path
import sys


def install_guard(*, read_roots, output):
    roots = tuple(Path(p).resolve() for p in read_roots)
    destination = Path(output).resolve()
    write_root = destination.parent

    def within(path, root):
        return path == root or root in path.parents

    def guard(event, args):
        if event.startswith("socket.") or event in {"subprocess.Popen", "os.system", "os.posix_spawn", "os.exec", "os.fork"}:
            raise PermissionError("offline_research_network_and_process_creation_forbidden")
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0])).resolve()
            mode,flags = args[1],args[2]
            writing = (isinstance(mode,str) and any(c in mode for c in "wax+")) or (
                isinstance(flags,int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)))
            if writing and not within(path,write_root):
                raise PermissionError("offline_research_write_outside_output_forbidden")
            if not writing and (path.name.startswith(".env") or not any(within(path,r) for r in roots)):
                raise PermissionError("offline_research_unapproved_read_forbidden")
        if event in {"os.remove", "os.mkdir", "os.rmdir", "os.chmod"} and isinstance(args[0],(str,bytes,os.PathLike)):
            if not within(Path(os.fsdecode(args[0])).resolve(),write_root):
                raise PermissionError("offline_research_mutation_outside_output_forbidden")
        if event in {"os.rename", "os.link", "os.symlink"}:
            if any(not within(Path(os.fsdecode(p)).resolve(),write_root) for p in args[:2]):
                raise PermissionError("offline_research_mutation_outside_output_forbidden")
    sys.addaudithook(guard)


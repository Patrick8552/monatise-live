"""-I bootstrap: no credentials, networking, broker/publisher or external writes."""
from pathlib import Path
import sys
import zoneinfo


if __name__ == "__main__":
    mode,source,repository,input_file,output_file = sys.argv[1:]
    source,repository,input_file,output_file = map(Path,(source,repository,input_file,output_file))
    sys.dont_write_bytecode = True
    sys.path.insert(0,str(source if mode == "replay" else repository))
    import monatise.research
    if mode == "replay": monatise.research.__path__.append(str(repository/"monatise/research"))
    from monatise.research.gold_retrospective.runner import verify_research_checkout
    verify_research_checkout(source)
    from monatise.research.gc_qualification.isolation import install_guard
    install_guard(read_roots=(source,repository,input_file,Path(sys.prefix),Path(sys.base_prefix),
                              Path(sys.executable).resolve().parents[1],output_file.parent,*zoneinfo.TZPATH),output=output_file)
    if mode == "prepare":
        from monatise.research.gc_qualification.prepare import prepare
        print(prepare(input_file,output_file,repository=repository),flush=True)
    elif mode == "replay":
        from monatise.research.gc_qualification.worker import main
        main(input_file,output_file)
    else:
        raise ValueError("unknown_offline_mode")

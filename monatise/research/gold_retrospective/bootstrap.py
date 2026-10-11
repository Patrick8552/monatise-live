"""Executed with -I; extends only the offline research package search path."""
import sys
from pathlib import Path

if __name__ == "__main__":
    h1_root, phase4_root, input_file, output_file = map(Path,sys.argv[1:])
    sys.path.insert(0,str(h1_root))
    import monatise.research
    monatise.research.__path__.append(str(phase4_root/"monatise/research"))
    # Application/engines/Gold-Fib all come from the pinned existing checkout;
    # the new archive/retrospective modules are the sole path extension.
    from monatise.research.gold_retrospective.runner import verify_research_checkout
    verify_research_checkout(h1_root)
    from monatise.research.gold_retrospective.worker import main
    main(input_file,output_file)

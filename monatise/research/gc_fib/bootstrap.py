"""Executed with -I: engines and selector from the frozen checkout only."""
import sys
from pathlib import Path

if __name__ == "__main__":
    h1, research, input_file, output_file = map(Path,sys.argv[1:])
    sys.path.insert(0,str(h1))
    import monatise.research
    monatise.research.__path__.append(str(research/"monatise/research"))
    from monatise.research.gold_retrospective.runner import verify_research_checkout
    verify_research_checkout(h1)
    from monatise.research.gc_fib.worker import main
    main(input_file,output_file)

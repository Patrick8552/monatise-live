"""-I bootstrap: frozen Gold code, current isolated research adapters, no secrets."""
from pathlib import Path
import sys

if __name__=='__main__':
    frozen,research,input_path,output_path=map(Path,sys.argv[1:])
    sys.path.insert(0,str(frozen))
    import monatise.research
    monatise.research.__path__.append(str(research/'monatise/research'))
    from monatise.research.gold_retrospective.runner import verify_research_checkout
    verify_research_checkout(frozen)
    from monatise.research.institutional.phase8.spot_worker import main
    main(input_path,output_path)

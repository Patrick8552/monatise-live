"""Bounded read-only request phrases and exact contract resolution; no AI/API."""
from pathlib import Path
import re


def request_symbols(text):
    if not isinstance(text,str) or len(text)>200:raise ValueError('bounded_analysis_phrase_required')
    match=re.fullmatch(r'\s*(?:analyse|analyze)\s+(.+?)\s+(?:using|with|from)\s+databento(?:\s+live(?:\s+data)?(?:\s+feeds?)?)?[.!]?\s*',text,re.I)
    if not match:raise ValueError('supported_read_only_analysis_phrase_required')
    words=re.split(r'\s*(?:,|\band\b)\s*|\s+',match.group(1),flags=re.I)
    symbols=tuple(w.upper() for w in words if w)
    if not 1<=len(symbols)<=3 or len(set(symbols))!=len(symbols) or any(s not in {'GC','ES','NQ'} for s in symbols):
        raise ValueError('only_distinct_GC_ES_NQ_analysis_supported')
    return symbols


def exact_symbols(symbols,pipeline):
    known={g.contract.metadata.raw_symbol:g.contract.metadata.product for g in pipeline.gates.values()}
    result=[]
    for symbol in symbols:
        if symbol in known:result.append(symbol);continue
        matches=[raw for raw,product in known.items() if product==symbol]
        if len(matches)!=1:raise ValueError('explicit_unique_loaded_contract_required:'+symbol)
        result.append(matches[0])
    if len(set(result))!=len(result):raise ValueError('duplicate_resolved_contract')
    return tuple(result)


def capture_from_pointer(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>4096:
        raise ValueError('bounded_regular_capture_pointer_required')
    root=Path(path.read_text().strip())
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ValueError('existing_absolute_capture_directory_required')
    return root

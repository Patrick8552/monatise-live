"""Permanent asset boundary for the canonical crypto candle engines."""
import re


def require_canonical_non_futures(symbol):
    value=str(symbol).upper().rsplit(':',1)[-1]
    if re.fullmatch(r'(?:GC|ES|NQ)(?:[FGHJKMNQUVXZ][0-9]{1,4}|[1-9][0-9]*!|=F|[.](?:FUT|[CNV][.]\d+))?',value):
        raise ValueError('native_futures_require_dedicated_native_analysis')

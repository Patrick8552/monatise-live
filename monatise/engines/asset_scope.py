"""Permanent asset boundary for the canonical crypto candle engines."""
import re


def require_canonical_non_futures(symbol):
    full=str(symbol).upper()
    value=full.rsplit(':',1)[-1]
    if re.fullmatch(r'(?:GC|ES|NQ)(?:[FGHJKMNQUVXZ][0-9]{1,4}|[1-9][0-9]*!|=F|[.](?:FUT|[CNV][.]\d+))?',value):
        raise ValueError('native_futures_require_dedicated_native_analysis')
    # BTC alone is also a spot/perpetual asset name. Only explicit futures
    # identities are rejected here; the user's request router selects product.
    if (full in {'CME:BTC','CME_GLOBEX:BTC'} or re.fullmatch(
            r'BTC(?:[FGHJKMNQUVXZ][0-9]{1,4}|[1-9][0-9]*!|=F|[.](?:FUT|[CNV][.]\d+))',value)):
        raise ValueError('native_futures_require_dedicated_native_analysis')

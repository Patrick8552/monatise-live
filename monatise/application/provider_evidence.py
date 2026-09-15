"""Allowlisted provider diagnostics; never persist arbitrary exception bodies."""
import math
import re
from datetime import datetime, timezone

GAMMA_STATUSES = frozenset({"available", "no_boundary", "stored_sign_mismatch",
    "insufficient_local_coverage", "insufficient_quote_quality", "sensitive_root",
    "uncertain_root_path", "search_budget", "quality_budget"})
FEEDS = ("equity_feed", "equity_options_feed", "index_feed", "index_options_feed",
         "futures_feed", "futures_options_feed")
FIELDS = ("underlying_price", "gamma_flip", "call_wall", "put_wall", "net_gex")


class EvidenceValidationError(ValueError):
    def __init__(self, message, *, field, issue, endpoint=None):
        super().__init__(message)
        self.field, self.issue, self.endpoint = field, issue, endpoint


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def gamma_status(value):
    return value if isinstance(value, str) and value in GAMMA_STATUSES else "unknown"


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _field_state(value, *, positive=True):
    if value is None:
        return "null_or_missing"
    if not _number(value):
        return "invalid_number"
    return "non_positive" if positive and value <= 0 else "valid"


def flashalpha_diagnostics(context=None, error=None):
    context = context if isinstance(context, dict) else {}
    result = {"provider": "flashalpha", "status": "rejected" if error else "received",
              "gamma_flip_status": gamma_status(context.get("gamma_flip_status")),
              "fields": {key: _field_state(context.get(key), positive=key != "net_gex") for key in FIELDS},
              "endpoints": {}}
    for name in ("gex", "levels"):
        raw = (context.get("provider_evidence") or {}).get(name)
        if not isinstance(raw, dict):
            continue
        row = {key: raw.get(key) for key in ("http_status", "attempts") if isinstance(raw.get(key), int)}
        row["http_statuses"] = [x for x in raw.get("http_statuses", []) if isinstance(x, int)][:3]
        symbol = raw.get("symbol")
        row["response_symbol"] = symbol if isinstance(symbol, str) and re.fullmatch(r"[A-Za-z0-9.=_-]{1,24}", symbol) else None
        row["gamma_flip_status"] = gamma_status(raw.get("gamma_flip_status"))
        parsed = timestamp(raw.get("as_of"))
        row["as_of"] = parsed.isoformat() if parsed else None
        feeds = raw.get("data_as_of") or {}
        row["data_as_of"] = {key: parsed.isoformat() if (parsed := timestamp(feeds.get(key))) else None
                             for key in FEEDS if isinstance(feeds, dict) and key in feeds}
        version = raw.get("endpoint_version")
        if isinstance(version, str) and re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", version):
            row["endpoint_version"] = version
        limits = raw.get("rate_limit") or {}
        row["rate_limit"] = {key: limits[key] for key in ("daily_limit", "remaining", "retry_after_seconds")
                             if isinstance(limits.get(key), int) or limits.get(key) == "unlimited"}
        result["endpoints"][name] = row
    if isinstance(error, EvidenceValidationError):
        result["failure"] = {"field": error.field, "issue": error.issue, "endpoint": error.endpoint}
    elif error:
        # All provider messages can contain arbitrary text. Preserve typed codes
        # and numeric transport metadata only.
        result["failure"] = {"issue": "provider_request_failed"}
        for key, attr in (("http_status", "status_code"), ("attempts", "attempts")):
            value = getattr(error, attr, None)
            if isinstance(value, int): result["failure"][key] = value
        if getattr(error, "endpoint", None) in {"gex", "levels"}:
            result["failure"]["endpoint"] = error.endpoint
    return result

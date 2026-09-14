"""Durable scanner runs and correlation IDs without credentials or account data."""
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
import hashlib
import secrets

RUNS = "ftmo_scanner_runs_v1"
RUN_ID = ContextVar("scanner_run_id", default=None)


def stamp_analysis(result, symbol):
    run_id = RUN_ID.get()
    if run_id:
        result["scanner_run_id"] = run_id
        result.setdefault("analysis_id", hashlib.sha256(f"{run_id}:{symbol}".encode()).hexdigest())
    return result


def analysis_trace(result):
    fields = ("asset", "symbol", "ftmo_symbol", "publication_id", "setup_state", "trigger_state",
              "shadow_outcome", "duplicate_blocked", "telegram_publication_failed", "layers_observed", "analysis_id", "scanner_run_id", "decision", "direction",
              "setup_status", "score", "score_threshold", "signal_core_score", "signal_core_evidence",
              "reason_code", "reason_detail", "reasons", "suppression_reasons", "pipeline_stage", "proposal_id",
              "telegram_message_id", "telegram_publish_status", "timeframe_policy", "analysis_timeframe",
              "confirmation_timeframe", "trigger_timeframe", "generated_at", "expires_at")
    value = {key: result.get(key) for key in fields if result.get(key) is not None}
    quote = result.get("ftmo_execution_quote") or {}
    value["quote"] = {key: quote.get(key) for key in ("status", "reason", "observed_at", "symbol") if quote.get(key) is not None}
    value["providers"] = [{key: item.get(key) for key in ("provider", "status", "failure_reason", "timeframes")}
                          for item in result.get("analysis_sources") or []]
    return value


def audited_scan(asset_class):
    def decorate(function):
        @wraps(function)
        async def wrapped(self, *args, **kwargs):
            run_id = secrets.token_hex(16)
            token = RUN_ID.set(run_id)
            store = getattr(self, "document_store", None) or getattr(getattr(getattr(self, "ftmo_master", None), "repository", None), "store", None)
            started = datetime.now(timezone.utc).isoformat()
            record = {"run_id": run_id, "asset_class": asset_class, "started_at": started, "status": "running"}
            try:
                if store:
                    await store.put(RUNS, run_id, record, expected_version=0)
                result = await function(self, *args, **kwargs)
                result["run_id"] = run_id
                result["started_at"] = started
                result["finished_at"] = datetime.now(timezone.utc).isoformat()
                result["pipeline_status"] = "degraded" if (
                    result.get("failures") or result.get("analysis_failure_count")
                    or result.get("snapshot_batch_failures")
                    or result.get("context_only_published")
                    or any(row.get("pipeline_stage") in {"DATA_REJECTED", "PUBLICATION_FAILED", "CONTEXT_ONLY"}
                           or row.get("telegram_publication_failed") for row in result.get("results", []))
                    or (result.get("excluded") or {}).get("provider_unavailable_fail_closed")
                ) else "healthy"
                record.update(status=result["pipeline_status"], finished_at=result["finished_at"],
                    summary={k: v for k, v in result.items() if isinstance(v, (int, float, bool, str))},
                    exclusions=result.get("excluded", {}), suppressions=result.get("suppressions", {}),
                    failures=result.get("failures", []), universe=result.get("universe_audit", []),
                    instruments=[analysis_trace(row) for row in result.get("results", [])])
                if store:
                    await store.put(RUNS, run_id, record, expected_version=1)
                return result
            except BaseException as exc:
                record.update(status="interrupted" if isinstance(exc, BaseException) and not isinstance(exc, Exception) else "failed",
                              finished_at=datetime.now(timezone.utc).isoformat(), error_type=type(exc).__name__)
                if store:
                    await store.put(RUNS, run_id, record, expected_version=1)
                raise
            finally:
                RUN_ID.reset(token)
        return wrapped
    return decorate

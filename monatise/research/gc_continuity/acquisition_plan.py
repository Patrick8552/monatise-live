"""Exact missing-evidence proposals and free metadata only; no acquisition method."""
from dataclasses import asdict
import time

from monatise.research.databento.acquisition import HistoricalRequest


def propose(report, *, ledger, archive):
    requests = []
    for item in report["missing_minutes"]:
        # Some October holes have already acquired trade requests. Rebuying them
        # would not add independent continuity evidence and is never proposed.
        if item["trade_requests"] or item["classification"] != "E": continue
        request = HistoricalRequest("GLBX.MDP3","trades",((1,41271,"GCZ6"),),
            item["start_ns"],item["end_ns"],record_limit=50_000,wire_byte_limit=8*1024**2)
        cache = ledger.plan(request,archive=archive)
        requests.append(dict(request=asdict(request),request_sha256=request.sha256,cache=cache,
            priority=1 if item["utc"] == "2026-09-21T04:37:00+00:00" else 2,
            purpose="DISTINGUISH_NO_TRADE_FROM_MISSING_EXECUTED_ACTIVITY",
            estimated_usd=None,estimate_status="FRESH_METADATA_REQUIRED",entitlement="UNVERIFIED",
            continuity_attestation_required_for_recovery=True,download_authorized=False))
    requests.sort(key=lambda r:(r["priority"],r["request"]["start_ns"]))
    return dict(schema="gc-continuity-acquisition-proposals-v1",requests=requests,
        approved_new_budget_usd=ledger.report()["approved_budget_usd"],
        general_credit_permission_recorded=True,concrete_nonzero_budget_approved=False,
        fresh_credit_balance_verified=False,estimated_cost_is_not_provider_charge_cap=True,
        acquisition_receipts_created=0,downloads_attempted=0,
        approval_required="Exact fresh estimate, credit/account entitlement review, concrete credit-only amount and residual uncapped exposure approval; no cash authorized.")


def metadata_only(plan, source, *, now_ns=None):
    """Injected metadata seam for offline tests; never calls a data endpoint."""
    now_ns = time.time_ns() if now_ns is None else now_ns
    value = dict(plan);value["requests"] = []
    for item in plan["requests"]:
        data = dict(item["request"]);data["contracts"] = tuple(tuple(c) for c in data["contracts"])
        request = HistoricalRequest(**data)
        proof = source.preflight(request,now_ns=now_ns)
        value["requests"].append({**item,"preflight":asdict(proof),"preflight_sha256":proof.sha256,
            "estimated_usd":proof.estimated_usd,"estimate_status":"METADATA_ESTIMATE_NOT_CHARGE_CAP",
            "download_authorized":False})
    return value

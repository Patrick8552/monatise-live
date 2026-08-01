from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone

from monatise.application.composition import create_application
from monatise.application.deployment import OrchestrationASGI
from monatise.application.staging_analysis import build_paper_analysis_run
from tests.test_application_real_pipeline import CandleProvider, MacroProvider


class Coordination:
    def __init__(self): self.claims = set()
    async def claim_nonce(self, value):
        if value in self.claims: return False
        self.claims.add(value); return True


class Runtime:
    def __init__(self, environment):
        self.environment = environment
        self.redis_coordination = Coordination()
        self.calls = []
    async def analyse(self, symbol, correlation_id=None, scenario="live"):
        self.calls.append((symbol, correlation_id, scenario))
        return {"symbol": symbol, "status": "blocked", "classification": "no_trade", "execution_enabled": False}


def request(runtime, payload, *, signed=True):
    body = json.dumps(payload, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(b"staging-secret", timestamp.encode() + b"." + body, hashlib.sha256).hexdigest() if signed else "bad"
    messages = []
    async def receive(): return {"type": "http.request", "body": body, "more_body": False}
    async def send(message): messages.append(message)
    scope = {"type": "http", "method": "POST", "path": "/api/staging/analyse", "headers": [(b"x-monatise-timestamp", timestamp.encode()), (b"x-monatise-signature", signature.encode())]}
    asyncio.run(OrchestrationASGI(runtime)(scope, receive, send))
    return messages[0]["status"], json.loads(messages[1]["body"])


def test_staging_analysis_requires_signature_and_rejects_order_parameters():
    runtime = Runtime({"MONATISE_ENVIRONMENT": "staging", "MONATISE_STAGING_API_TOKEN": "staging-secret"})
    assert request(runtime, {"symbol": "BTC"}, signed=False)[0] == 401
    code, payload = request(runtime, {"symbol": "BTC", "leverage": 2})
    assert code == 400 and "only symbol" in payload["reason"]
    assert runtime.calls == []


def test_staging_analysis_is_disabled_outside_staging():
    runtime = Runtime({"MONATISE_ENVIRONMENT": "production", "MONATISE_STAGING_API_TOKEN": "staging-secret"})
    assert request(runtime, {"symbol": "BTC"})[0] == 404


def test_staging_analysis_accepts_only_supported_signed_analysis():
    runtime = Runtime({"MONATISE_ENVIRONMENT": "staging", "MONATISE_STAGING_API_TOKEN": "staging-secret"})
    code, payload = request(runtime, {"symbol": "BTC", "scenario": "no_trade"})
    assert code == 200 and payload["execution_enabled"] is False
    assert runtime.calls == [("BTC", None, "no_trade")]


def test_controlled_scenarios_stop_at_decision_and_governance():
    application = create_application(market_data_providers={"mock": CandleProvider(datetime.now(timezone.utc))}, macro_provider=MacroProvider())
    no_trade = asyncio.run(application.orchestrator.run(build_paper_analysis_run("BTC", scenario="no_trade")))
    assert no_trade.blocked_by == "decision" and "risk_validation" not in no_trade.context.outputs
    governance = asyncio.run(application.orchestrator.run(build_paper_analysis_run("BTC", scenario="governance_block")))
    assert governance.blocked_by == "governance_loss_control"
    assert governance.statistics.completed_stages == 20

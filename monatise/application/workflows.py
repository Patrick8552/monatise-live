"""OpenClaw scheduling and Telegram delivery workflows (analysis-only)."""

from __future__ import annotations

import inspect
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from datetime import timedelta
from typing import Any, Awaitable, Callable, Protocol

from monatise.application.models import AnalysisRun, PipelineResult
from monatise.application.orchestrator import PipelineOrchestrator
from monatise.application.production_analysis import build_directional_plan, build_moving_grid_plan, build_setup_validity, strongest_confirmation_signal
from monatise.application.registry import CANONICAL_ENGINE_ORDER, PRODUCTION_ENGINE_ORDER
from monatise.application.time_display import format_nigeria_time
from monatise.infrastructure.state_manager import StateKey
from monatise.infrastructure.task_scheduler import JobDefinition, RetryPolicy, ScheduleType


class TelegramTransport(Protocol):
    async def send_message(self, chat_id: str, text: str) -> Any: ...


class TelegramNotifier:
    def __init__(self, transport: TelegramTransport, chat_id: str) -> None:
        if not isinstance(chat_id, str) or not chat_id.strip():
            raise ValueError("Telegram chat_id is required")
        self._transport, self._chat_id = transport, chat_id

    async def deliver(self, result: PipelineResult) -> Any:
        text = self.format(result)
        return await self._transport.send_message(self._chat_id, text)

    async def deliver_grid_cancellation(self, result: PipelineResult, reason: str) -> Any:
        market = result.context.outputs.get("market_data")
        interval = getattr(market, "interval", "unknown")
        text = "\n".join((
            f"Monatise GRID ENTRY CANCELLED: {result.symbol}",
            f"Timeframe: {interval}",
            _current_price_line(market),
            f"Entry: CANCELLED — {reason}",
            f"Status: {result.status.value}",
            f"Run: {result.run_id}",
        ))
        return await self._transport.send_message(self._chat_id, text)

    async def deliver_grid_replacement(self, result: PipelineResult) -> Any:
        directional = self.format(result)
        text = "\n".join((
            f"Monatise GRID ENTRY CANCELLED: {result.symbol}",
            "Reason: replaced by the directional setup below",
            "",
            directional,
        ))
        return await self._transport.send_message(self._chat_id, text)

    async def deliver_setup_expiry(self, result: PipelineResult, expired_at: str) -> Any:
        market = result.context.outputs.get("market_data")
        interval = getattr(market, "interval", "unknown")
        text = "\n".join((
            f"Monatise DIRECTIONAL SETUP EXPIRED: {result.symbol}",
            f"Timeframe: {interval}",
            _current_price_line(market),
            f"Expired at: {expired_at}",
            "Entry: CANCELLED — the setup validity window ended",
            f"Run: {result.run_id}",
        ))
        return await self._transport.send_message(self._chat_id, text)

    async def deliver_safely(self, result: PipelineResult) -> bool:
        try:
            await self.deliver(result)
            return True
        except Exception:
            return False

    async def governance_alert(self, message: str) -> Any:
        return await self._alert("GOVERNANCE", message)

    async def health_alert(self, message: str) -> Any:
        return await self._alert("HEALTH", message)

    async def audit_notification(self, message: str) -> Any:
        return await self._alert("AUDIT", message)

    async def hierarchy_shadow_notification(self, message: str) -> Any:
        if not message.strip():
            raise ValueError("notification message is required")
        return await self._transport.send_message(self._chat_id, message)

    async def x_macro_notification(self, message: str) -> Any:
        if not message.strip():
            raise ValueError("notification message is required")
        return await self._transport.send_message(self._chat_id, f"Monatise X INTELLIGENCE\n{message}")

    async def coin_discovery_notification(self, message: str) -> Any:
        if not message.strip():
            raise ValueError("notification message is required")
        return await self._transport.send_message(self._chat_id, f"Monatise COINGLASS SCANNER\n{message}")

    async def dynamic_analysis_notification(self, message: str) -> Any:
        if not message.strip():
            raise ValueError("notification message is required")
        return await self._transport.send_message(self._chat_id, f"Monatise DYNAMIC ANALYSIS\n{message}")

    async def stock_analysis_notification(self, message: str) -> Any:
        if not message.strip():
            raise ValueError("notification message is required")
        return await self._transport.send_message(self._chat_id, f"Monatise STOCK ANALYSIS\n{message}")

    async def command_response(self, message: str) -> Any:
        if not message.strip():
            raise ValueError("command response is required")
        return await self._transport.send_message(self._chat_id, message)

    async def register_webhook(self, url: str, secret_token: str) -> bool:
        register = getattr(self._transport, "set_webhook", None)
        if register is None:
            raise RuntimeError("Telegram transport does not support webhooks")
        return bool(await register(url, secret_token))

    async def _alert(self, category: str, message: str) -> Any:
        if not message.strip():
            raise ValueError("notification message is required")
        return await self._transport.send_message(self._chat_id, f"Monatise {category}: {message}")

    @staticmethod
    def format(result: PipelineResult) -> str:
        outputs = result.context.outputs
        decision = outputs.get("decision")
        market = outputs.get("market_data")
        stage_inputs = set(getattr(result.context.run, "stage_inputs", {}))
        stage_total = len(PRODUCTION_ENGINE_ORDER) if stage_inputs == set(PRODUCTION_ENGINE_ORDER) else len(CANONICAL_ENGINE_ORDER)

        classification = _enum_value(getattr(decision, "classification", "no_trade")).upper() if decision is not None else None
        decision_metadata = (getattr(decision, "metadata", {}) or {}) if decision is not None else {}
        signed_score = int(decision_metadata.get("signed_signal_score", 0) or 0)
        grid_score = int(decision_metadata.get("grid_signal_score", 0) or 0)
        threshold = int(decision_metadata.get("minimum_signal_score", 7) or 7)
        if classification in {"GRID", "TWO_SIDED"}:
            classification = "NO_TRADE"
        if classification == "NO_TRADE":
            reasons = tuple(getattr(decision, "reasons", ()) or ())[:3]
            lines = [
                f"Monatise NO_TRADE: {result.symbol}",
                f"Status: {result.status.value} | stages {result.statistics.completed_stages}/{stage_total}",
                _current_price_line(market),
                f"Score: {signed_score:+d}/10 | trade threshold: ±{threshold}",
            ]
            if reasons:
                lines.append("Why: " + "; ".join(str(reason) for reason in reasons))
            blockers = tuple(getattr(decision, "blockers", ()) or ())[:3]
            if blockers:
                lines.append("Blocked by: " + "; ".join(str(blocker) for blocker in blockers))
            lines.append(f"Run: {result.run_id}")
            return "\n".join(lines)

        if decision is None:
            suffix = f" | blocked by {result.blocked_by}" if result.blocked_by else ""
            return (
                f"Monatise analysis: {result.symbol} | {result.status.value} | "
                f"stages {result.statistics.completed_stages}/{stage_total}{suffix} | "
                f"{_current_price_line(market).casefold()} | run {result.run_id}"
            )

        direction = _enum_value(getattr(decision, "direction", "none")).upper()
        classification = _enum_value(getattr(decision, "classification", "no_trade")).upper()
        conviction = float(getattr(decision, "conviction", 0.0) or 0.0)
        analysis_plan = build_directional_plan(getattr(market, "price", None), direction)
        entry = analysis_plan["entry"] if analysis_plan else None
        stop = analysis_plan["invalidation"] if analysis_plan else None
        target = analysis_plan["target"] if analysis_plan else None
        quality = getattr(market, "quality", None)
        source = getattr(quality, "source", "CoinGlass")
        interval = getattr(market, "interval", "unknown")
        reasons = tuple(getattr(decision, "reasons", ()) or ())[:3]

        price_action = outputs.get("price_action")
        confirmation_status = _enum_value(getattr(price_action, "status", "pending")).upper()
        grid_state = {
            "CONFIRMED": "ENTRY READY",
            "PENDING": "DECISION READY",
            "CONFLICT": "ACTIVE ENTRY BLOCKED",
            "EXPIRED": "REFRESH REQUIRED",
            "INVALIDATED": "ACTIVE ENTRY BLOCKED",
        }.get(confirmation_status, "DECISION REVIEW")
        heading = (
            f"Monatise GRID {grid_state} — ENTRY CONFIRMATION {confirmation_status}: {result.symbol} ({direction})"
            if classification == "GRID"
            else f"Monatise directional setup: {result.symbol} {direction} ({classification})"
        )
        lines = [
            heading,
            f"Timeframe: {interval}",
            _current_price_line(market),
            f"Score: {grid_score}/10" if classification == "GRID" else f"Score: {signed_score:+d}/10",
            f"Confidence: {conviction * 100:.0f}%",
        ]
        confirmation_signal = strongest_confirmation_signal(price_action)
        confirmation_age = int(getattr(confirmation_signal, "age_candles", 0) or 0)
        validity = build_setup_validity(
            interval,
            getattr(result, "finished_at", result.context.run.requested_at),
            age_candles=confirmation_age if classification == "GRID" else 0,
        )
        if validity is not None and (classification != "GRID" or confirmation_status == "CONFIRMED"):
            # Preserve a positive sub-second remainder instead of truncating it
            # to zero at the formatting boundary.
            remaining_seconds = max(0, math.ceil((validity["expires_at"] - datetime.now(timezone.utc)).total_seconds()))
            remaining_label = "<1 min" if 0 < remaining_seconds < 60 else f"{math.ceil(remaining_seconds / 60)} min"
            lines.extend((
                f"Generated at: {format_nigeria_time(validity['generated_at'])}",
                f"Valid until: {format_nigeria_time(validity['expires_at'])}",
                f"Remaining validity: {remaining_label} | {validity['remaining_candles']} candle(s)",
            ))
        if classification == "GRID":
            grid = build_moving_grid_plan(market)
            if grid is None:
                lines.append("Grid levels: unavailable")
            else:
                lines.extend([
                    f"Center: {_price(grid['center'])}",
                    "Buy levels: " + " | ".join(_price(value) for value in grid["buy_levels"]),
                    "Sell levels: " + " | ".join(_price(value) for value in grid["sell_levels"]),
                    f"Boundaries: {_price(grid['lower_boundary'])} — {_price(grid['upper_boundary'])}",
                    f"Invalidation: below {_price(grid['lower_invalidation'])} or above {_price(grid['upper_invalidation'])}",
                    f"Spacing: {_price(grid['spacing'])} | {grid['levels_per_side']} levels per side",
                ])
            confirming = tuple(getattr(price_action, "confirming_signals", ()) or ())
            conflicts = tuple(getattr(price_action, "conflicting_signals", ()) or ())
            confirmation_reasons = tuple(getattr(price_action, "reasons", ()) or ())
            if confirmation_status == "CONFIRMED":
                strongest = getattr(confirmation_signal, "pattern", None) or getattr(price_action, "strongest_confirming_pattern", None) or "price action"
                age = int(getattr(confirmation_signal, "age_candles", 0) or 0)
                lines.append(f"Entry confirmation: {strongest} | confidence {float(getattr(price_action, 'aggregate_confidence', 0)) * 100:.0f}% | aligned families {getattr(price_action, 'aligned_family_count', 0)} | age {age} candle(s)")
            elif confirmation_status == "CONFLICT":
                bullish = max((s for s in (*confirming, *conflicts) if s.direction.value == "bullish"), key=lambda s: s.confidence, default=None)
                bearish = max((s for s in (*confirming, *conflicts) if s.direction.value == "bearish"), key=lambda s: s.confidence, default=None)
                lines.append(f"Entry: WAIT — conflicting evidence: bullish {getattr(bullish, 'pattern', 'none')} | bearish {getattr(bearish, 'pattern', 'none')}")
            elif confirmation_status == "EXPIRED":
                lines.append("Entry: WAIT — previous trigger expired; a fresh price-action trigger is required")
            elif confirmation_status == "INVALIDATED":
                lines.append("Entry: WAIT — price-action setup invalidated; a new setup is required")
            else:
                reason = confirmation_reasons[0] if confirmation_reasons else "fresh confirmation is required at the selected grid level"
                lines.append(f"Entry: WAIT — {reason}")
        else:
            lines.append(f"Projected entry: {_price(entry)} | Invalidation: {_price(stop)} | Target: {_price(target)}")
        lines.append(f"Data: {source} | Status: {result.status.value}")
        if reasons:
            lines.append("Why: " + "; ".join(str(reason) for reason in reasons))
        lines.append(f"Run: {result.run_id}")
        return "\n".join(lines)

    @staticmethod
    def format_dynamic_analysis(analysis: dict[str, Any]) -> str:
        """Format the sanitized+finalized dict from analyse_dynamic_coinglass.

        Distinct dict shape from `format(PipelineResult)` — dynamic analysis
        adds entry_zone/targets/data_quality/provenance/volatility_assessment
        fields that a raw PipelineResult does not carry.
        """
        symbol = analysis.get("symbol", "UNKNOWN")
        classification = str(analysis.get("classification") or "no_trade").upper()
        direction = str(analysis.get("direction") or "none").upper()
        if classification == "GRID" or direction == "TWO_SIDED":
            classification = "NO_TRADE"
            direction = "NONE"
        provenance = analysis.get("provenance") or {}
        quality = analysis.get("data_quality") or {}
        evidence = analysis.get("evidence") or {}
        interval = analysis.get("interval", "unknown")

        lines = [
            f"Monatise dynamic scan: {symbol} {direction} ({classification})",
            f"Timeframe: {interval}",
        ]
        instrument = provenance.get("instrument")
        exchange = provenance.get("exchange")
        if instrument and exchange:
            lines.append(f"Resolved market: {instrument} on {exchange} (verified via {provenance.get('source', 'CoinGlass')})")
        price = evidence.get("current_price")
        if price is not None:
            lines.append(f"Current price: {_price(price)}")

        if not quality.get("passed", True):
            lines.append("Status: NO_TRADE — quality gate failed")
            failures = tuple(quality.get("failures") or ())[:3]
            if failures:
                lines.append("Why: " + "; ".join(str(item) for item in failures))
        else:
            zone = analysis.get("entry_zone")
            if zone:
                lines.append(f"Entry zone: {_price(zone.get('low'))} — {_price(zone.get('high'))} (trigger required, not an automatic entry)")
                lines.append(f"Trigger: {analysis.get('entry_trigger', 'confirmation required')}")
            if analysis.get("invalidation") is not None:
                lines.append(f"Invalidation: {_price(analysis['invalidation'])}")
            targets = analysis.get("targets") or []
            if targets:
                lines.append("Targets: " + " | ".join(_price(item) for item in targets))
            if analysis.get("reward_risk") is not None:
                lines.append(f"Reward:risk: {analysis['reward_risk']:.2f}")

        score = analysis.get("score")
        if score is not None:
            score_text = f"{score:+d}/10"
            lines.append(f"Score: {score_text} | trade threshold: ±{analysis.get('score_threshold', 7)}")

        warnings = tuple(quality.get("warnings") or ())[:3]
        if warnings:
            lines.append("Warnings: " + "; ".join(str(item) for item in warnings))

        assessment = analysis.get("volatility_assessment")
        if assessment:
            lines.append(f"Note: {assessment}")

        if analysis.get("expires_at"):
            lines.append(f"Expires: {analysis['expires_at']}")

        lines.append(f"Run: {analysis.get('run_id', 'n/a')}")
        return "\n".join(lines)

    @staticmethod
    def format_stock_analysis(analysis: dict[str, Any]) -> str:
        """Format the Quiver-backed stock analysis dict from analyse_stock.

        Mirrors analyze_stock.py's on-demand OpenClaw skill formatter (same
        field names, same layout) so the autonomous scan and on-demand
        queries read the same way.
        """
        asset = analysis.get("asset", "UNKNOWN")
        decision = str(analysis.get("decision") or "NO_TRADE")
        lines = [
            f"Monatise stock scan: {asset} ({decision.replace('_', ' ')})",
            f"Quiver score: {int(analysis.get('score') or 0):+d}/10 | threshold: ±{int(analysis.get('score_threshold') or 3)}",
        ]
        reasons = list(analysis.get("reasons") or [])[:4]
        cautions = list(analysis.get("cautions") or [])[:3]
        if reasons:
            lines += ["Evidence:", *[f"• {item}" for item in reasons]]
        if cautions:
            lines += ["Cautions:", *[f"• {item}" for item in cautions]]
        if analysis.get("setup_status") == "confirmed":
            lines += [
                f"Entry: ${float(analysis['entry']):,.2f}",
                f"Stop: ${float(analysis['stop_loss']):,.2f}",
                f"Target: ${float(analysis['target']):,.2f}",
                f"Reward/risk: {float(analysis['reward_risk']):.2f}",
                f"Levels: {analysis.get('level_source', 'Alpaca market data')}",
            ]
        elif decision in {"BUY_WATCH", "SELL_WATCH"}:
            lines.append("Price confirmation pending; no entry or stop is active.")
        additional = analysis.get("additional_context") or {}
        if additional.get("quote"):
            lines.append(f"Finnhub validation: ${float(additional['quote']):,.2f} | {int(additional.get('news_count') or 0)} recent news items")
        lines += [
            "Quiver alternative-data watch signal only.",
            "No trade was executed; confirm price structure, entry, invalidation, and risk before acting.",
        ]
        return "\n".join(lines)

    @staticmethod
    def format_flashalpha_futures_analysis(analysis: dict[str, Any]) -> str:
        asset = analysis.get("asset", "UNKNOWN")
        direction = str(analysis.get("direction") or "NONE")
        lines = [
            f"Monatise CME futures setup: {asset} {direction}",
            f"FlashAlpha score: {int(analysis.get('score') or 0):+d}/10 | threshold: ±{int(analysis.get('score_threshold') or 7)}",
            f"Entry: {_price(analysis.get('entry'))}",
            f"Invalidation / gamma flip: {_price(analysis.get('stop_loss'))}",
            f"Target / {'call' if direction == 'LONG' else 'put'} wall: {_price(analysis.get('target'))}",
            f"Reward/risk: {float(analysis.get('reward_risk') or 0):.2f}",
        ]
        if analysis.get("net_gex_label"):
            lines.append(f"Gamma regime: {analysis['net_gex_label']}")
        lines += [
            "Source: FlashAlpha CME options-on-futures positioning (Black-76).",
            "Notification only; no trade was executed.",
        ]
        return "\n".join(lines)

    @staticmethod
    def format_market_stock_setup(analysis: dict[str, Any]) -> str:
        direction = str(analysis.get("direction") or "NONE").upper()
        asset = str(analysis.get("asset") or "UNKNOWN")
        name = str(analysis.get("company_name") or asset)
        targets = analysis.get("targets") or [analysis.get("target")]
        lines = [
            f"Monatise US stock setup: {asset} — {name}",
            f"Direction: {direction}",
            f"Monatise score: {int(analysis.get('score') or 0):+d}/10 | threshold: ±{int(analysis.get('score_threshold') or 7)}",
            f"Current: {_price(analysis.get('current_price'))}",
            f"Entry: {_price(analysis.get('entry'))}",
            f"Trigger: {analysis.get('confirmation_trigger', 'confirmed technical trigger')}",
            f"Invalidation: {_price(analysis.get('stop_loss'))}",
            "Targets: " + " | ".join(_price(item) for item in targets if item is not None),
            f"Reward/risk: {float(analysis.get('reward_risk') or 0):.2f}",
            f"Timeframe: {analysis.get('timeframe', '1h / 1d')}",
            f"Valid until: {analysis.get('valid_until', 'n/a')}",
        ]
        reasons = list(analysis.get("reasons") or [])[:5]
        if reasons:
            lines.append("Technical hierarchy: " + "; ".join(str(reason) for reason in reasons))
        context = analysis.get("additional_context") or {}
        quiver = context.get("quiver") or {}
        quiver_summary = quiver.get("summary") or {}
        lines.append(
            f"Quiver: {int(quiver_summary.get('score') or 0):+d}/10 — "
            + ("; ".join(str(item) for item in (quiver_summary.get("drivers") or [])[:3]) or "no fresh directional insider/Congress evidence")
        )
        flashalpha = context.get("flashalpha") or {}
        if not flashalpha.get("unavailable") and flashalpha.get("gamma_flip") is not None:
            lines.append(
                f"FlashAlpha: flip {_price(flashalpha.get('gamma_flip'))} | call wall {_price(flashalpha.get('call_wall'))} | "
                f"put wall {_price(flashalpha.get('put_wall'))} | regime {flashalpha.get('net_gex_label') or 'n/a'}"
            )
        finnhub = context.get("finnhub") or {}
        warnings = []
        if finnhub.get("earnings"): warnings.append("earnings calendar event present")
        if finnhub.get("news"): warnings.append(f"{len(finnhub['news'])} recent company-news items")
        if warnings: lines.append("News/event context: " + "; ".join(warnings))
        freshness = analysis.get("data_freshness") or {}
        lines.append(f"Freshness: latest hourly bar {freshness.get('latest_hourly_bar', 'n/a')}")
        lines += [
            "Sources: Monatise technical hierarchy; Alpaca market data; Quiver/Finnhub/FlashAlpha where available.",
            "Notification only; no trade was executed.",
        ]
        return "\n".join(lines)

    @property
    def execution_enabled(self) -> bool:
        return False


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _price(value: Any) -> str:
    if value is None:
        return "pending"
    return f"{float(value):,.8f}".rstrip("0").rstrip(".")


def _current_price_line(market: Any) -> str:
    metadata = getattr(market, "metadata", {}) or {}
    price_type = metadata.get("price_type", "reference")
    label = "Current CoinGlass price" if price_type == "current" and metadata.get("price_source") == "coinglass" else "Current reference price"
    observed_at = metadata.get("price_observed_at")
    source = metadata.get("price_source")
    details = [f"source {source}" if source else "", f"observed {observed_at}" if observed_at else ""]
    suffix = " | " + " | ".join(detail for detail in details if detail) if any(details) else ""
    return f"{label}: {_price(getattr(market, 'price', None))}{suffix}"


@dataclass(frozen=True)
class OpenClawWorkflow:
    orchestrator: PipelineOrchestrator
    run_factory: Callable[[], AnalysisRun | Awaitable[AnalysisRun]]
    notifier: TelegramNotifier | None = None
    maximum_request_age_seconds: float = 300.0

    def __post_init__(self) -> None:
        if self.maximum_request_age_seconds <= 0:
            raise ValueError("maximum_request_age_seconds must be positive")
        if not callable(self.run_factory):
            raise ValueError("run_factory must be callable")

    async def schedule(self, scheduler: Any, *, job_id: str, interval_seconds: float, state: Any | None = None) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")

        async def task() -> PipelineResult:
            if state is not None:
                await state.set(StateKey("openclaw_workflows", job_id), {"status": "running", "updated_at": datetime.now(timezone.utc).isoformat()})
            try:
                result = await self.execute()
            except Exception:
                if state is not None:
                    await state.set(StateKey("openclaw_workflows", job_id), {"status": "failed", "updated_at": datetime.now(timezone.utc).isoformat()})
                raise
            if state is not None:
                await state.set(StateKey("openclaw_workflows", job_id), {"status": result.status.value, "run_id": result.run_id, "updated_at": datetime.now(timezone.utc).isoformat()})
            return result

        await scheduler.register(JobDefinition(job_id, f"OpenClaw crypto analysis {job_id}", task, ScheduleType.INTERVAL, interval=timedelta(seconds=interval_seconds), retry_policy=RetryPolicy(maximum_attempts=3), tags=("openclaw", "crypto", "analysis"), metadata={"execution_enabled": False}))

    async def execute(self) -> PipelineResult:
        candidate = self.run_factory()
        run = await candidate if inspect.isawaitable(candidate) else candidate
        if not isinstance(run, AnalysisRun):
            raise TypeError("run_factory must return AnalysisRun")
        age = (datetime.now(timezone.utc) - run.requested_at).total_seconds()
        if age < -60:
            raise ValueError("scheduled analysis request is in the future")
        if age > self.maximum_request_age_seconds:
            raise ValueError("scheduled analysis request is stale")
        result = await self.orchestrator.run(run)
        if self.notifier is not None:
            await self.notifier.deliver_safely(result)
        return result

    @property
    def execution_enabled(self) -> bool:
        return False

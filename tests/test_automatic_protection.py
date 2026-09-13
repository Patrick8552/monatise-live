from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

import pytest

from monatise.application.ftmo_master import (
    FTMOMasterControlService,
    format_proposal,
)
from monatise.application.position_management import PositionManagementService
from monatise.application.take_profit import TakeProfitPlan
from tests.test_multi_tp import config, deal, execution_setup, open_position, plan
from tests.test_ftmo_master import NOW, heartbeat


async def protection_setup(monkeypatch, *, trailing=False, automatic=True):
    control, store, proposal = await execution_setup(monkeypatch, auto=True)
    policy = config(
        auto_partial_close=True,
        auto_breakeven=not trailing,
        auto_trailing=trailing,
        breakeven_mode="NONE" if trailing else "AFTER_TP1",
        trail_mode="STRUCTURE_TRAIL" if trailing else "OFF",
    )
    control.configuration = replace(control.configuration, multi_tp=policy)
    stored, version = await control.repository.proposal(proposal["proposal_id"])
    ladder = replace(
        TakeProfitPlan.from_dict(stored["take_profit_plan"]),
        breakeven_policy=policy.breakeven_mode,
        trail_policy=policy.trail_mode,
        automatic_stop_management=automatic,
    )
    stored.update(
        take_profit_plan=ladder.to_dict(), preview_plan_digest=ladder.digest()
    )
    await control.repository.update_proposal(stored["proposal_id"], stored, version)
    position, opening = await open_position(control, stored)
    manager = PositionManagementService(control)
    deals = []
    for index in range(2 if trailing else 1):
        state, _ = await manager.get(stored["proposal_id"])
        target = state.plan.targets[index]
        hb = heartbeat(multi_tp_version=1, positions=[position], deals=list(deals))
        hb["quotes"]["XAUUSD"].update(
            bid=str(target.price), ask=str(target.price + D(".2"))
        )
        await control.accept_bridge_heartbeat(hb, now=NOW)
        state, _ = await manager.get(stored["proposal_id"])
        partial = (await control.repository.proposal(state.pending_proposal_id))[0]
        assert (
            partial["operation"] == "partial_close" and partial["automatic_management"]
        )
        deals.append(
            deal(
                800 + index,
                partial["volume"],
                comment="MNT:" + partial["command_id"][:16],
            )
        )
        position = dict(
            position, volume=str(D(position["volume"]) - D(partial["volume"]))
        )
        await control.acknowledge(
            partial["command_id"],
            dict(
                status="reconciled",
                broker_retcode="10009",
                broker_ticket=str(800 + index),
                executed_volume=partial["volume"],
                fill_price=str(target.price),
                submission_attempted=True,
            ),
        )
        hb.update(positions=[position], deals=list(deals))
        await control.accept_bridge_heartbeat(hb, now=NOW)
        state, _ = await manager.get(stored["proposal_id"])
        assert state.plan.targets[index].status == "HIT"
        assert state.pending_proposal_id is None  # No fresh structure: no stop move.
    evidence = dict(
        source="monatise.test.structure",
        confirmed=True,
        direction="long",
        observed_at=NOW.isoformat(),
        confirmed_higher_low="2510",
    )
    await manager.record_structure("XAUUSD", evidence)
    return control, manager, stored, hb, evidence


def test_legacy_plan_digest_and_automatic_scope_are_distinct():
    old = plan().to_dict()
    assert "automatic_stop_management" not in old
    digest = hashlib.sha256(
        json.dumps(old, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert TakeProfitPlan.from_dict(old).digest() == digest
    automatic = replace(
        plan(), automatic_stop_management=True, breakeven_policy="AFTER_TP1"
    )
    assert automatic.digest() != digest
    assert TakeProfitPlan.from_dict(automatic.to_dict()).automatic_stop_management
    with pytest.raises(ValueError, match="management policy"):
        TakeProfitPlan.from_dict(dict(old, automatic_stop_management="false"))


@pytest.mark.parametrize("trailing", [False, True])
@pytest.mark.parametrize("automatic", [False, True])
def test_protection_follows_original_scope_and_reconciles_once(
    monkeypatch, trailing, automatic
):
    async def run():
        control, manager, original, hb, _ = await protection_setup(
            monkeypatch, trailing=trailing, automatic=automatic
        )
        preview = format_proposal(original)
        assert ("automatic within this approved policy" in preview) is automatic
        result = await control.accept_bridge_heartbeat(hb, now=NOW)
        state, _ = await manager.get(original["proposal_id"])
        stop = (await control.repository.proposal(state.pending_proposal_id))[0]
        assert stop["operation"] == "sl"
        assert stop["value"] == (
            "2509.99" if trailing else hb["positions"][0]["price_open"]
        )
        if not automatic:
            assert stop.get("command_id") is None
            assert stop["proposal_id"] in result["management_proposal_ids"]
            return
        assert stop["command_id"] and stop["automatic_management"]
        assert stop["proposal_id"] not in result["management_proposal_ids"]
        assert (
            stop["scope_approval_id"]
            == (await control.repository.proposal(original["proposal_id"]))[0][
                "approval_id"
            ]
        )
        queued = await control.commands_for_bridge(now=NOW)
        assert [c["operation"] for c in queued] == ["sl"]
        control = FTMOMasterControlService(control.configuration, control.repository)
        await control.accept_bridge_heartbeat(hb, now=NOW)
        assert len(await control.repository.pending_commands()) == 1
        await control.acknowledge(
            stop["command_id"],
            dict(
                status="reconciled",
                broker_retcode="10009",
                broker_ticket="123",
                executed_stop_loss=stop["value"],
                submission_attempted=True,
            ),
        )
        hb["positions"][0]["sl"] = stop["value"]
        await control.accept_bridge_heartbeat(hb, now=NOW)
        manager = PositionManagementService(control)
        state, _ = await manager.get(original["proposal_id"])
        assert (
            state.current_sl == D(stop["value"]) and state.pending_proposal_id is None
        )
        await control.accept_bridge_heartbeat(hb, now=NOW)
        assert not await control.repository.pending_commands()

    asyncio.run(run())


@pytest.mark.parametrize(
    "gate", ["route", "automatic", "kill", "scope", "evidence", "stale", "milestone"]
)
@pytest.mark.parametrize("trailing", [False, True])
def test_queued_automatic_stop_rechecks_authority_and_conditions(
    monkeypatch, gate, trailing
):
    async def run():
        control, manager, original, hb, evidence = await protection_setup(
            monkeypatch, trailing=trailing
        )
        await control.accept_bridge_heartbeat(hb, now=NOW)
        state, version = await manager.get(original["proposal_id"])
        stop = (await control.repository.proposal(state.pending_proposal_id))[0]
        assert stop["command_id"]
        if gate in {"route", "automatic"}:
            changes = (
                {"routes": frozenset()}
                if gate == "route"
                else {"auto_trailing" if trailing else "auto_breakeven": False}
            )
            control.configuration = replace(
                control.configuration,
                multi_tp=replace(control.configuration.multi_tp, **changes),
            )
        elif gate == "kill":
            await control.repository.update_control(kill_switch=True)
        elif gate == "scope":
            parent, version = await control.repository.proposal(original["proposal_id"])
            parent["take_profit_plan"].pop("automatic_stop_management")
            await control.repository.update_proposal(
                parent["proposal_id"], parent, version
            )
        elif gate == "evidence":
            await manager.record_structure("XAUUSD", dict(evidence, invalidated=True))
        elif gate == "stale":
            stop, version = await control.repository.proposal(stop["proposal_id"])
            stop["structure_evidence"]["observed_at"] = (
                NOW - timedelta(minutes=6)
            ).isoformat()
            await control.repository.update_proposal(stop["proposal_id"], stop, version)
        else:
            state.plan = replace(
                state.plan,
                targets=tuple(replace(t, status="PENDING") for t in state.plan.targets),
            )
            await manager.save(state, version)
        assert not await control.commands_for_bridge(now=NOW)

    asyncio.run(run())


def test_automatic_stop_reservation_recovers_after_process_restart(monkeypatch):
    async def run():
        control, manager, original, hb, _ = await protection_setup(monkeypatch)
        saved = control.repository.save_proposal

        async def crash(proposal):
            if proposal.get("management_policy"):
                raise RuntimeError("simulated stop after durable reservation")
            return await saved(proposal)

        monkeypatch.setattr(control.repository, "save_proposal", crash)
        with pytest.raises(RuntimeError):
            await manager.advance(
                original["proposal_id"],
                (await control.repository.proposal(original["proposal_id"]))[0],
                hb,
                NOW,
            )
        reserved, _ = await manager.get(original["proposal_id"])
        assert reserved.pending_intent["automatic_management"]
        monkeypatch.setattr(control.repository, "save_proposal", saved)
        control = FTMOMasterControlService(control.configuration, control.repository)
        await control.accept_bridge_heartbeat(hb, now=NOW)
        recovered = (await control.repository.proposal(reserved.pending_proposal_id))[0]
        assert recovered["command_id"]
        assert len(await control.repository.pending_commands()) == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "breakeven,trailing,automatic",
    [
        ("NONE", "OFF", False),
        ("AFTER_TP1", "OFF", True),
        ("NONE", "STRUCTURE_TRAIL", True),
    ],
)
def test_new_plan_records_configured_automatic_authority(
    breakeven, trailing, automatic
):
    from monatise.application.take_profit import MultiTPConfiguration, build_plan
    from tests.test_multi_tp import evidence

    policy = MultiTPConfiguration.from_environment(
        dict(
            AUTO_PARTIAL_CLOSE_ENABLED="true",
            AUTO_BREAKEVEN_ENABLED="true",
            AUTO_TRAILING_ENABLED="true",
            MULTI_TP_BREAKEVEN_MODE=breakeven,
            MULTI_TP_TRAIL_MODE=trailing,
        )
    )
    result = build_plan(
        candidates=[evidence(110)],
        direction="long",
        entry=100,
        stop=95,
        now=NOW,
        expires_at=NOW + timedelta(minutes=30),
        config=policy,
    )
    assert result.automatic_stop_management is automatic
    assert result.management_mode == "APPROVED_PLAN"
    assert result.breakeven_policy == breakeven and result.trail_policy == trailing

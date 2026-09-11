import asyncio
from datetime import datetime, timedelta

import pytest

from monatise.application.ftmo_master import EA_PRICE_TOLERANCE_REASON, FTMOMasterError
from tests.test_ftmo_master import heartbeat
from tests.test_telegram_approval_window import prepare, callback, bridge_request


def move_price(app, control, clock, price):
    payload = heartbeat()
    payload['quotes']['XAUUSD'].update(bid=str(price), ask=str(price + .2), timestamp=clock[0].isoformat())
    bridge_request(app, control, clock[0], 'POST', '/api/ftmo/bridge/heartbeat', payload)


def pending_child(control, parent):
    saved = asyncio.run(control.repository.proposal(parent['proposal_id']))[0]
    return asyncio.run(control.repository.proposal(saved['replacement_proposal_id']))[0]


@pytest.mark.parametrize('action', ['approve', 'reject'])
def test_server_price_refusal_offers_one_limit_with_independent_manual_approval(monkeypatch, action):
    app, control, _, original, transport, message_id, clock = prepare(monkeypatch, 'scanner')
    clock[0] += timedelta(minutes=20)
    move_price(app, control, clock, 2515)
    assert callback(app, original, message_id, 'approve')[0] == 200
    child = pending_child(control, original)
    assert child['status'] == 'pending_confirmation' and child['order_type'] == 'limit'
    assert child['proposal_id'] != original['proposal_id']
    for key in ('entry', 'stop_loss', 'take_profit', 'expires_at'):
        assert child[key] == original[key]
    assert child['approval_keyboard_attached'] is True
    assert 'NEW LIMIT ORDER' in transport.proposals[-1][1]
    assert asyncio.run(control.repository.pending_commands()) == ()
    assert callback(app, original, message_id, 'approve', update_id=124)[0] == 200
    assert len(transport.proposals) == 2
    assert len(asyncio.run(control.repository.proposals())) == 2
    assert asyncio.run(control.repository.pending_commands()) == ()
    assert callback(app, child, child['telegram_message_id'], action, update_id=125)[0] == 200
    commands = asyncio.run(control.commands_for_bridge(now=clock[0]))
    assert len(commands) == int(action == 'approve')
    if commands:
        assert commands[0]['proposal_id'] == child['proposal_id']
        assert commands[0]['payload']['order_type'] == 'limit'
        assert commands[0]['payload']['entry'] == original['entry']
        assert commands[0]['payload']['pending_expires_epoch'] == str(int(datetime.fromisoformat(original['expires_at']).timestamp()))
    callback(app, original, message_id, 'approve', update_id=126)
    assert len(transport.proposals) == 2


@pytest.mark.parametrize('side,price,stop,target', [('buy', 2515, '2490.20', '2530.20'), ('sell', 2485, '2510.00', '2470.00')])
def test_mt5_pre_submission_refusal_offers_limit_and_reconciles_pending_ack(monkeypatch, side, price, stop, target):
    app, control, _, _, transport, _, clock = prepare(monkeypatch, 'scanner')
    original = asyncio.run(control.create_trade_proposal(
        actor='42', symbol='XAUUSD', side=side, order_type='market', stop_loss=stop, take_profit=target,
    ))
    message_id = asyncio.run(app.runtime.telegram.trade_proposal('preview', original['proposal_id']))
    callback(app, original, message_id, 'approve')
    command = asyncio.run(control.repository.pending_commands())[0]
    bridge_request(app, control, clock[0], 'GET', '/api/ftmo/bridge/commands')
    move_price(app, control, clock, price)
    refused = {'status': 'rejected', 'submission_attempted': False, 'message': EA_PRICE_TOLERANCE_REASON}
    ack_path = f"/api/ftmo/bridge/commands/{command['command_id']}/ack"
    assert bridge_request(app, control, clock[0], 'POST', ack_path, refused)['command_status'] == 'rejected'
    child = pending_child(control, original)
    assert child['side'] == side and child['order_type'] == 'limit'
    assert child['entry'] == command['payload']['entry']
    assert asyncio.run(control.commands_for_bridge(now=clock[0])) == ()
    count = len(transport.proposals)
    bridge_request(app, control, clock[0], 'POST', ack_path, refused)
    bridge_request(app, control, clock[0], 'POST', ack_path, dict(refused, message='duplicate delivery reconciled from EA journal'))
    assert len(transport.proposals) == count
    callback(app, child, child['telegram_message_id'], 'approve', update_id=124)
    limit = asyncio.run(control.commands_for_bridge(now=clock[0]))[0]
    assert limit['payload']['order_type'] == 'limit'
    accepted = {'status': 'reconciled', 'broker_retcode': '10008', 'broker_ticket': '789', 'submission_attempted': True}
    assert bridge_request(app, control, clock[0], 'POST', f"/api/ftmo/bridge/commands/{limit['command_id']}/ack", accepted)['command_status'] == 'reconciled'


@pytest.mark.parametrize('mutation', [
    {'status': 'broker_uncertain'}, {'submission_attempted': True}, {'submission_attempted': None},
    {'broker_retcode': '10020'}, {'broker_ticket': '789'}, {'fill_price': '2500.2'},
    {'message': 'not enough money'},
])
def test_uncertain_or_different_broker_failures_never_offer_replacement(monkeypatch, mutation):
    app, control, _, original, transport, message_id, clock = prepare(monkeypatch, 'scanner')
    callback(app, original, message_id, 'approve')
    command = asyncio.run(control.repository.pending_commands())[0]
    move_price(app, control, clock, 2515)
    payload = {'status': 'rejected', 'submission_attempted': False, 'message': EA_PRICE_TOLERANCE_REASON, **mutation}
    bridge_request(app, control, clock[0], 'POST', f"/api/ftmo/bridge/commands/{command['command_id']}/ack", payload)
    assert len(transport.proposals) == 1
    assert len(asyncio.run(control.repository.proposals())) == 1


@pytest.mark.parametrize('price', [2485, 2530])
def test_wrong_side_or_target_reached_cannot_become_a_limit(monkeypatch, price):
    app, control, _, original, transport, message_id, clock = prepare(monkeypatch, 'scanner')
    move_price(app, control, clock, price)
    callback(app, original, message_id, 'approve')
    assert len(transport.proposals) == 1
    assert len(asyncio.run(control.repository.proposals())) == 1
    assert asyncio.run(control.repository.pending_commands()) == ()


@pytest.mark.parametrize('failure', ['expired', 'superseded', 'crossed_market', 'target_reached', 'kill_switch'])
def test_replacement_approval_rechecks_original_and_current_market(monkeypatch, failure):
    app, control, _, original, _, message_id, clock = prepare(monkeypatch, 'scanner')
    move_price(app, control, clock, 2515)
    callback(app, original, message_id, 'approve')
    child = pending_child(control, original)
    if failure == 'expired':
        clock[0] += timedelta(minutes=30)
    elif failure == 'superseded':
        parent, version = asyncio.run(control.repository.proposal(original['proposal_id']))
        parent['superseded_by_signal_id'] = 'new-signal'
        asyncio.run(control.repository.update_proposal(original['proposal_id'], parent, version))
    elif failure == 'crossed_market':
        move_price(app, control, clock, 2499)
    elif failure == 'target_reached':
        move_price(app, control, clock, 2530)
    else:
        asyncio.run(control.repository.update_control(kill_switch=True))
    callback(app, child, child['telegram_message_id'], 'approve', update_id=124)
    assert asyncio.run(control.repository.pending_commands()) == ()
    assert len(asyncio.run(control.repository.proposals())) == 2


def test_uncertain_submission_cannot_later_become_replacement_eligible(monkeypatch):
    app, control, _, original, transport, message_id, clock = prepare(monkeypatch, 'scanner')
    callback(app, original, message_id, 'approve')
    command = asyncio.run(control.repository.pending_commands())[0]
    path = f"/api/ftmo/bridge/commands/{command['command_id']}/ack"
    move_price(app, control, clock, 2515)
    bridge_request(app, control, clock[0], 'POST', path, {'status': 'broker_uncertain'})
    refused = {'status': 'rejected', 'submission_attempted': False, 'message': EA_PRICE_TOLERANCE_REASON}
    bridge_request(app, control, clock[0], 'POST', path, refused)
    bridge_request(app, control, clock[0], 'POST', path, refused)
    assert len(transport.proposals) == 1
    assert len(asyncio.run(control.repository.proposals())) == 1


def test_unpublished_replacement_cannot_be_approved(monkeypatch):
    app, control, _, original, _, _, clock = prepare(monkeypatch, 'scanner')
    move_price(app, control, clock, 2515)
    with pytest.raises(FTMOMasterError, match='tolerance'):
        asyncio.run(control.approve(original['proposal_id'], '42'))
    child = asyncio.run(control.create_limit_replacement(original['proposal_id'], actor='42'))
    with pytest.raises(FTMOMasterError, match='publication'):
        asyncio.run(control.approve(child['proposal_id'], '42'))
    assert asyncio.run(control.repository.pending_commands()) == ()


def test_concurrent_replacement_creation_produces_one_child(monkeypatch):
    app, control, _, original, _, _, clock = prepare(monkeypatch, 'scanner')
    move_price(app, control, clock, 2515)
    with pytest.raises(FTMOMasterError):
        asyncio.run(control.approve(original['proposal_id'], '42'))
    async def create_both():
        return await asyncio.gather(*(control.create_limit_replacement(original['proposal_id'], actor='42') for _ in range(2)), return_exceptions=True)
    results = asyncio.run(create_both())
    children = [item for item in results if isinstance(item, dict)]
    assert children and len({child['proposal_id'] for child in children}) == 1
    assert len(asyncio.run(control.repository.proposals())) == 2
    assert asyncio.run(control.repository.pending_commands()) == ()


def test_later_original_fill_evidence_blocks_queued_replacement_delivery(monkeypatch):
    app, control, _, original, _, message_id, clock = prepare(monkeypatch, 'scanner')
    callback(app, original, message_id, 'approve')
    command = asyncio.run(control.repository.pending_commands())[0]
    move_price(app, control, clock, 2515)
    path = f"/api/ftmo/bridge/commands/{command['command_id']}/ack"
    bridge_request(app, control, clock[0], 'POST', path, {
        'status': 'rejected', 'submission_attempted': False, 'message': EA_PRICE_TOLERANCE_REASON,
    })
    child = pending_child(control, original)
    callback(app, child, child['telegram_message_id'], 'approve', update_id=124)
    assert len(asyncio.run(control.repository.pending_commands())) == 1
    bridge_request(app, control, clock[0], 'POST', path, {
        'status': 'reconciled', 'submission_attempted': True, 'broker_retcode': '10009',
        'broker_ticket': '789', 'fill_price': '2500.2', 'executed_volume': '.3',
    })
    assert bridge_request(app, control, clock[0], 'GET', '/api/ftmo/bridge/commands')['count'] == 0

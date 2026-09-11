"""Regress the zero-price DONE receipt observed in the second demo test."""

import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest

from tests.test_ftmo_master import heartbeat
from tests.test_telegram_approval_window import prepare, callback, bridge_request


def submitted(monkeypatch, *, retcode='10009', acknowledge=True):
    app, control, store, proposal, transport, message_id, clock = prepare(monkeypatch, 'operator')
    callback(app, proposal, message_id, 'approve')
    assert bridge_request(app, control, clock[0], 'GET', '/api/ftmo/bridge/commands')['count'] == 1
    command = asyncio.run(control.repository.pending_commands())[0]
    receipt = {'status': 'broker_uncertain', 'broker_ticket': '9001', 'broker_retcode': retcode,
               'fill_price': '0.00', 'executed_volume': command['payload']['volume'],
               'submission_attempted': True, 'message': 'done at 0.00'}
    ack_path = f"/api/ftmo/bridge/commands/{command['command_id']}/ack"
    if acknowledge:
        bridge_request(app, control, clock[0], 'POST', ack_path, receipt)
    clock[0] += timedelta(seconds=2)
    payload = heartbeat(observed_at_utc=clock[0].isoformat())
    payload['quotes']['XAUUSD']['timestamp'] = clock[0].isoformat()
    payload['positions'] = [{
        'ticket': '9001', 'comment': f"MNT:{command['command_id'][:16]}", 'symbol': 'XAUUSD',
        'type': 0, 'volume': command['payload']['volume'], 'price_open': '2500.18',
        'price_current': '2500.40', 'sl': proposal['stop_loss'], 'tp': proposal['take_profit'],
    }]
    return app, control, store, proposal, transport, clock, command, payload, ack_path, receipt


def test_signed_heartbeat_confirms_zero_price_receipt_and_updates_telegram_once(monkeypatch):
    app, control, store, proposal, transport, clock, command, payload, ack_path, receipt = submitted(monkeypatch)
    assert any('FTMO EXECUTION CHECK PENDING' in text and 'Fill: pending' in text for _, text in transport.messages)
    assert not any('FTMO EXECUTION FAILED' in text for _, text in transport.messages)
    result = bridge_request(app, control, clock[0], 'POST', '/api/ftmo/bridge/heartbeat', payload)
    assert result['lifecycle_events'][0]['execution_reconciled'] is True
    confirmed = asyncio.run(control.repository.command(command['command_id']))[0]
    assert confirmed['status'] == 'reconciled'
    assert confirmed['fill_price'] == '2500.18'
    assert confirmed['executed_volume'] == command['payload']['volume']
    assert confirmed['reconciliation_source'] == 'mt5_position_heartbeat'
    assert confirmed['limit_replacement_eligible'] is False
    saved = asyncio.run(control.repository.proposal(proposal['proposal_id']))[0]
    assert saved['status'] == 'reconciled' and saved['lifecycle_state'] == 'POSITION_OPEN'
    assert any('EXECUTED — POSITION OPEN' in text and '2500.18' in text for _, _, text in transport.retractions)
    count = len(transport.messages), len(transport.retractions)
    bridge_request(app, control, clock[0], 'POST', '/api/ftmo/bridge/heartbeat', payload)
    bridge_request(app, control, clock[0], 'POST', ack_path, receipt)
    assert (len(transport.messages), len(transport.retractions)) == count
    assert asyncio.run(control.repository.command(command['command_id']))[0]['fill_price'] == '2500.18'
    assert asyncio.run(control.repository.pending_commands()) == ()
    assert len(asyncio.run(store.list_namespace(control.repository.COMMANDS))) == 1


@pytest.mark.parametrize('failure', [
    'ticket', 'comment', 'symbol', 'side', 'partial_volume', 'zero_price', 'nan_price',
    'missing_timestamp', 'stale_timestamp', 'future_timestamp', 'before_command',
    'disconnected', 'wrong_account', 'partial_retcode',
])
def test_unmatched_or_incomplete_position_cannot_confirm_execution(monkeypatch, failure):
    app, control, _, _, _, clock, command, payload, _, _ = submitted(
        monkeypatch, retcode='10010' if failure == 'partial_retcode' else '10009',
    )
    position = payload['positions'][0]
    if failure == 'ticket': position['ticket'] = '9002'
    elif failure == 'comment': position['comment'] = 'unrelated'
    elif failure == 'symbol': position['symbol'] = 'AAPL'
    elif failure == 'side': position['type'] = 1
    elif failure == 'partial_volume': position['volume'] = str(Decimal(position['volume']) / 2)
    elif failure == 'zero_price': position['price_open'] = '0'
    elif failure == 'nan_price': position['price_open'] = 'NaN'
    elif failure == 'missing_timestamp': payload.pop('observed_at_utc')
    elif failure == 'stale_timestamp': payload['observed_at_utc'] = (clock[0] - timedelta(seconds=60)).isoformat()
    elif failure == 'future_timestamp': payload['observed_at_utc'] = (clock[0] + timedelta(seconds=60)).isoformat()
    elif failure == 'before_command': payload['observed_at_utc'] = (clock[0] - timedelta(seconds=3)).isoformat()
    elif failure == 'disconnected': payload['terminal_connected'] = False
    elif failure == 'wrong_account':
        asyncio.run(control.repository.update_command(command['command_id'], {'expected_account_id': 'unrelated'}))
    bridge_request(app, control, clock[0], 'POST', '/api/ftmo/bridge/heartbeat', payload)
    saved = asyncio.run(control.repository.command(command['command_id']))[0]
    assert saved['status'] == 'broker_uncertain'
    assert saved.get('reconciliation_source') is None
    assert asyncio.run(control.repository.pending_commands()) == ()


def test_position_seen_before_receipt_is_reconciled_on_following_heartbeat(monkeypatch):
    app, control, _, proposal, _, clock, command, payload, ack_path, receipt = submitted(monkeypatch, acknowledge=False)
    bridge_request(app, control, clock[0], 'POST', '/api/ftmo/bridge/heartbeat', payload)
    bridge_request(app, control, clock[0], 'POST', ack_path, receipt)
    bridge_request(app, control, clock[0], 'POST', '/api/ftmo/bridge/heartbeat', payload)
    assert asyncio.run(control.repository.command(command['command_id']))[0]['status'] == 'reconciled'
    payload['positions'] = []
    bridge_request(app, control, clock[0], 'POST', '/api/ftmo/bridge/heartbeat', payload)
    bridge_request(app, control, clock[0], 'POST', ack_path, receipt)
    saved = asyncio.run(control.repository.proposal(proposal['proposal_id']))[0]
    assert saved['status'] == 'reconciled' and saved['lifecycle_state'] == 'POSITION_CLOSED'

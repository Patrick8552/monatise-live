"""Exercise delayed Telegram callbacks through the signed bridge HTTP boundary.

Telegram transport and broker fills are simulated; no external order is placed.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
from datetime import timedelta

import pytest

import monatise.application.ftmo_master as master_module
from monatise.application.ftmo_master import FTMOBridgeAuthenticator, FTMOMasterError
from monatise.application.production import ProductionASGI, telegram_webhook_secret
from monatise.application.workflows import TelegramNotifier
from tests.test_ftmo_master import NOW, heartbeat
from tests.test_production_entrypoint import Runtime, telegram_webhook
from tests.test_trade_publication import Transport, proposal, setup


def prepare(monkeypatch, kind):
    async def create():
        control, store = await setup(monkeypatch, FTMO_APPROVAL_QUOTE_WAIT_SECONDS='0')
        if kind == 'scanner':
            pending = await proposal(control)
        else:
            pending = await control.create_trade_proposal(
                actor='42', symbol='XAUUSD', side='buy', order_type='market',
                stop_loss='2490.20', take_profit='2520.20', now=NOW,
            )
        transport = Transport()
        notifier = TelegramNotifier(transport, '42', proposal_service=control)
        message_id = await notifier.trade_proposal('preview', pending['proposal_id'])
        return control, store, pending, transport, notifier, message_id

    control, store, pending, transport, notifier, message_id = asyncio.run(create())
    clock = [NOW]
    monkeypatch.setattr(master_module, '_utc', lambda value=None: value or clock[0])
    runtime = Runtime()
    runtime.ftmo_master, runtime.telegram = control, notifier
    runtime.environment.update({'MONATISE_TELEGRAM_BOT_TOKEN': 'test', 'MONATISE_TELEGRAM_CHAT_ID': '42'})
    app = ProductionASGI(runtime)
    return app, control, store, pending, transport, message_id, clock


def callback(app, pending, message_id, action, update_id=123):
    update = {
        'update_id': update_id,
        'callback_query': {
            'id': f'callback-{update_id}', 'from': {'id': 42},
            'data': f"ftmo:{action}:{pending['proposal_id']}",
            'message': {'message_id': message_id, 'chat': {'id': 42, 'type': 'private'}},
        },
    }
    return telegram_webhook(app, update, secret=telegram_webhook_secret('test'))


def bridge_request(app, control, now, method, path, payload=None):
    async def send_request():
        body = json.dumps(payload).encode() if payload is not None else b''
        timestamp, nonce = str(int(now.timestamp())), secrets.token_hex(16)
        signature = FTMOBridgeAuthenticator.sign(control.configuration.bridge_secret, method, path, timestamp, nonce, body)
        scope = {
            'type': 'http', 'method': method, 'path': path,
            'headers': [(b'x-monatise-timestamp', timestamp.encode()),
                        (b'x-monatise-nonce', nonce.encode()),
                        (b'x-monatise-signature', signature.encode())],
        }
        messages = []
        async def receive():
            return {'type': 'http.request', 'body': body, 'more_body': False}
        async def send(message):
            messages.append(message)
        await app(scope, receive, send)
        assert messages[0]['status'] == 200
        return json.loads(messages[1]['body'])
    return asyncio.run(send_request())


def refresh_bridge(app, control, now, *, stale=False, moved=False):
    payload = heartbeat()
    quote = payload['quotes']['XAUUSD']
    quote['timestamp'] = (NOW if stale else now).isoformat()
    if moved:
        quote.update(bid='2600.00', ask='2600.20')
    return bridge_request(app, control, now, 'POST', '/api/ftmo/bridge/heartbeat', payload)


@pytest.mark.parametrize('kind', ['operator', 'scanner'])
@pytest.mark.parametrize('action', ['approve', 'reject'])
@pytest.mark.parametrize('delay_seconds', [1799, 1800])
def test_thirty_minute_callbacks_through_webhook_and_signed_bridge(monkeypatch, kind, action, delay_seconds):
    app, control, store, pending, transport, message_id, clock = prepare(monkeypatch, kind)
    assert pending['expires_at'] == (NOW + timedelta(minutes=30)).isoformat()
    assert pending['expires_at'] in transport.proposals[0][1]
    assert bridge_request(app, control, clock[0], 'GET', '/api/ftmo/bridge/commands')['count'] == 0
    clock[0] += timedelta(seconds=delay_seconds)
    refresh_bridge(app, control, clock[0])
    assert callback(app, pending, message_id, action) == (200, {'status': 'accepted'})
    assert callback(app, pending, message_id, action) == (200, {'status': 'duplicate'})
    # Another physical click has a new update id but must not authorize a second command.
    assert callback(app, pending, message_id, 'approve', update_id=124) == (200, {'status': 'accepted'})
    result = bridge_request(app, control, clock[0], 'GET', '/api/ftmo/bridge/commands')
    approved = action == 'approve' and delay_seconds < 1800
    assert result['count'] == int(approved)
    saved = asyncio.run(control.repository.proposal(pending['proposal_id']))[0]
    assert saved['status'] == ('command_created' if approved else 'rejected' if action == 'reject' else 'expired')
    assert len([key for namespace, key in store.values if namespace == control.repository.COMMANDS]) == int(approved)
    assert transport.retractions[-1][1] == message_id
    if not approved:
        return
    signed = result['commands'][0]
    canonical = base64.b64decode(signed['payload_base64'])
    assert hmac.compare_digest(signed['signature'], hmac.new(control.configuration.bridge_secret.encode(), canonical, hashlib.sha256).hexdigest())
    command = json.loads(canonical)
    assert command['approval']['approved_by'] == '42'
    assert command['expires_at'] == pending['expires_at']  # Only one second remains.
    assert command['execution_snapshot']['quote_observed_at_utc'] == clock[0].isoformat()
    acknowledgement = {
        'status': 'reconciled', 'broker_ticket': '12345678', 'broker_retcode': '10009',
        'submission_attempted': True, 'requested_price': command['payload']['entry'],
        'fill_price': command['payload']['entry'], 'executed_volume': command['payload']['volume'],
        'executed_stop_loss': command['payload']['stop_loss'],
        'executed_take_profit': command['payload']['take_profit'],
    }
    response = bridge_request(app, control, clock[0], 'POST', f"/api/ftmo/bridge/commands/{command['command_id']}/ack", acknowledgement)
    assert response['command_status'] == 'reconciled'
    saved = asyncio.run(control.repository.proposal(pending['proposal_id']))[0]
    assert saved['broker_ticket'] == '12345678'
    assert saved['execution_result']['broker_retcode'] == '10009'
    assert any('FTMO EXECUTION CONFIRMATION' in text for _, text in transport.messages)
    assert bridge_request(app, control, clock[0], 'GET', '/api/ftmo/bridge/commands')['count'] == 0


@pytest.mark.parametrize('failure', ['stale_quote', 'price_moved'])
def test_delayed_approval_keeps_current_quote_and_price_validation(monkeypatch, failure):
    app, control, _, pending, transport, message_id, clock = prepare(monkeypatch, 'scanner')
    clock[0] += timedelta(minutes=29)
    refresh_bridge(app, control, clock[0], stale=failure == 'stale_quote', moved=failure == 'price_moved')
    assert callback(app, pending, message_id, 'approve')[0] == 200
    assert bridge_request(app, control, clock[0], 'GET', '/api/ftmo/bridge/commands')['count'] == 0
    assert asyncio.run(control.repository.pending_commands()) == ()
    assert any('BLOCKED' in text for _, text in transport.messages)


def test_explicit_signal_expiry_is_not_extended_by_the_approval_default(monkeypatch):
    async def scenario():
        control, _ = await setup(monkeypatch)
        pending = await proposal(control, signal_expires_at=NOW + timedelta(minutes=10))
        assert pending['expires_at'] == (NOW + timedelta(minutes=10)).isoformat()
        with pytest.raises(FTMOMasterError, match='expired'):
            await control.approve(pending['proposal_id'], '42', now=NOW + timedelta(minutes=10))
        assert await control.repository.pending_commands() == ()
    asyncio.run(scenario())


def test_management_preview_displays_the_thirty_minute_deadline(monkeypatch):
    async def scenario():
        control, _ = await setup(monkeypatch)
        await control.accept_bridge_heartbeat(heartbeat(positions=[{
            'ticket': '12345', 'symbol': 'XAUUSD', 'volume': '0.01',
            'price_open': '2500.20', 'sl': '2490.20', 'tp': '2520.20',
        }]), now=NOW)
        pending = await control.create_management_proposal(actor='42', operation='close', target_id='12345')
        assert pending['expires_at'] == (NOW + timedelta(minutes=30)).isoformat()
        assert pending['expires_at'] in master_module.format_proposal(pending)
        assert await control.repository.pending_commands() == ()
    asyncio.run(scenario())

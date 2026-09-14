import asyncio
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal

import pytest

from monatise.application.ftmo_master import FTMOMasterError, format_proposal
from monatise.application.hierarchy.approval import CURRENT
from monatise.application.entry_policy import entry_order_type
from monatise.application.workflows import TelegramNotifier
from tests.shared_hierarchy_fixtures import persist_proof
from tests.test_ftmo_master import heartbeat, active_environment, service
from tests.test_shared_timeframe_hierarchy import NOW
from tests.test_trade_publication import Transport


async def prepare(monkeypatch, *, symbol='AAPL', side='buy', price='105', capability=True, minimum='0'):
    monkeypatch.setattr('monatise.application.ftmo_master._utc', lambda value=None: value or NOW)
    control, store = service(active_environment(FTMO_TEMPORARY_ARM_REQUIRED='false'))
    await control.repository.update_control(kill_switch=False)
    quote = dict(heartbeat()['quotes']['XAUUSD'], bid=str(Decimal(price) - Decimal('.02')), ask=price,
                 timestamp=NOW.isoformat(), expiration_mode=4, stops_level=minimum)
    payload = heartbeat(quotes={symbol: quote}, pending_entry_version=2 if capability else None)
    await control.accept_bridge_heartbeat(payload, now=NOW)
    stop, target = ('90', '125') if side == 'buy' else ('110', '75')
    proof = await persist_proof(control, symbol, NOW, entry='100', stop=stop, target=target,
        direction='LONG' if side == 'buy' else 'SHORT', zone={'low': '99', 'high': '101'}, observed_price=price)
    if not proof:
        proof = {'market_price_observation': {'price': price, 'source': 'coinglass', 'kind': 'provider_reference', 'observed_at': NOW.isoformat()}}
    kwargs = dict(signal_id='waiting-1', symbol=symbol, direction='LONG' if side == 'buy' else 'SHORT',
        analysis_state='LONG' if side == 'buy' else 'SHORT', confirmation_status='confirmed',
        analysis_entry='100', analysis_stop=stop, analysis_target=target, entry_zone_low='99', entry_zone_high='101',
        analysis_provider='ftmo_mt5' if symbol != 'BTCUSD' else 'coinglass', source='monatise.test',
        evidence_bundle=proof, signal_expires_at=NOW + timedelta(minutes=10), now=NOW)
    proposal = await control.create_signal_proposal(**kwargs)
    return control, store, proposal, payload, kwargs


@pytest.mark.parametrize('side,price,kind', [('buy','105','limit'), ('buy','95','stop'), ('sell','95','limit'), ('sell','105','stop')])
@pytest.mark.parametrize('symbol', ['AAPL', 'US100.cash', 'BTCUSD'])
def test_waiting_entry_four_pending_types_keep_approval_and_real_price(monkeypatch, side, price, kind, symbol):
    async def scenario():
        control, _, proposal, _, kwargs = await prepare(monkeypatch, side=side, price=price, symbol=symbol)
        before = deepcopy(proposal)
        assert proposal['entry_status'] == 'WAITING_FOR_ENTRY' and proposal['order_type'] == kind
        assert proposal['status'] == 'pending_confirmation'
        assert proposal['evidence_bundle']['market_price_observation']['price'] == price
        assert proposal['quote_ask'] == price and Decimal(proposal['entry']) != Decimal(price)
        transport = Transport()
        notifier = TelegramNotifier(transport, '42', proposal_service=control)
        await notifier.trade_proposal('preview', proposal['proposal_id'])
        saved = (await control.repository.proposal(proposal['proposal_id']))[0]
        assert saved['approval_keyboard_attached'] and saved['telegram_publish_status'] == 'published'
        assert 'WAITING FOR ENTRY' in format_proposal(saved)
        assert await control.repository.pending_commands() == ()
        with pytest.raises(FTMOMasterError):
            await control.create_signal_proposal(**kwargs)
        command = await control.approve(proposal['proposal_id'], '42', now=NOW)
        assert command['payload']['order_type'] == kind
        for key in ('entry', 'stop_loss', 'take_profit'):
            assert command['payload'][key] == before[key]
        assert Decimal(command['risk_policy']['actual_risk_amount']) <= Decimal(before['risk_amount'])
        assert command['payload']['pending_expires_epoch'] == str(int((NOW + timedelta(minutes=10)).timestamp()))
        assert command['payload']['pending_entry_version'] == '2'
        with pytest.raises(FTMOMasterError):
            await control.approve(proposal['proposal_id'], '42', now=NOW)
        assert len(await control.commands_for_bridge(now=NOW)) == 1
    asyncio.run(scenario())


async def submitted(monkeypatch):
    control, store, proposal, payload, kwargs = await prepare(monkeypatch)
    command = await control.approve(proposal['proposal_id'], '42', now=NOW)
    await control.commands_for_bridge(now=NOW)
    payload['orders'] = [dict(ticket='7788', symbol=proposal['symbol'], magic='26082501', type=2,
        comment='MNP:' + command['command_id'][:16], price_open=proposal['entry'], sl=proposal['stop_loss'],
        tp=proposal['take_profit'], volume=proposal['volume'], expiration_epoch=command['payload']['pending_native_expires_epoch'])]
    return control, store, proposal, payload, command


@pytest.mark.parametrize('failure', ['expiry','hierarchy','kill','signal','analysis','target','stop','stale','spread','risk','size','protection','capability','type','session','superseded','native_expired','native_extended','native_missing'])
def test_pending_lease_revoked_on_loss_of_eligibility_and_never_restored(monkeypatch, failure):
    async def scenario():
        control, store, proposal, payload, command = await submitted(monkeypatch)
        result = await control.accept_bridge_heartbeat(payload, now=NOW)
        assert result['pending_entry_leases'].startswith('7788|')
        assert (await control.repository.command(command['command_id']))[0]['status'] == 'reconciled'
        assert await control.commands_for_bridge(now=NOW + timedelta(seconds=1)) == ()
        bad = deepcopy(payload)
        time = NOW
        if failure == 'expiry': time += timedelta(minutes=10)
        elif failure == 'hierarchy': await store.put(CURRENT, 'AAPL', {'state': 'invalidated'})
        elif failure == 'kill': await control.repository.update_control(kill_switch=True)
        elif failure == 'signal': await store.put(control.repository.SIGNALS, proposal['signal_id'], {'status': 'invalidated'})
        elif failure == 'analysis': await control.repository.update_telegram_analysis(proposal['analysis_id'], {'invalidated': True})
        elif failure in {'target','stop'}:
            bad['quotes']['AAPL'].update(bid='125' if failure=='target' else '89', ask='125.02' if failure=='target' else '89.02')
        elif failure == 'stale': bad['quotes']['AAPL']['timestamp'] = (NOW - timedelta(seconds=6)).isoformat()
        elif failure == 'spread': bad['quotes']['AAPL']['ask'] = '109'
        elif failure == 'risk': bad['equity'] = '9700'
        elif failure == 'size': bad['orders'][0]['volume'] = '50'
        elif failure == 'protection': bad['orders'][0]['sl'] = '89'
        elif failure == 'capability': bad['pending_entry_version'] = 0
        elif failure == 'native_expired': bad['orders'][0]['expiration_epoch'] = str(int(NOW.timestamp()))
        elif failure == 'native_extended': bad['orders'][0]['expiration_epoch'] = str(int(command['payload']['pending_native_expires_epoch']) + 1)
        elif failure == 'native_missing': bad['orders'][0].pop('expiration_epoch')
        elif failure == 'type': bad['orders'][0]['type'] = 4
        elif failure == 'session': bad['quotes']['AAPL']['trade_mode'] = 'disabled'
        elif failure == 'superseded':
            value, version = await control.repository.proposal(proposal['proposal_id'])
            await control.repository.update_proposal(proposal['proposal_id'], {**value, 'superseded_by_signal_id': 'new'}, version)
        result = await control.accept_bridge_heartbeat(bad, now=time)
        assert result['pending_entry_leases'] == ''
        saved = (await control.repository.proposal(proposal['proposal_id']))[0]
        assert saved['pending_entry_state'] == 'CANCELLATION_REQUIRED'
        assert saved['pending_cancellation_reason']
        await control.repository.update_control(kill_switch=False)
        assert (await control.accept_bridge_heartbeat(payload, now=NOW))['pending_entry_leases'] == ''
        assert await control.repository.pending_commands() == ()
    asyncio.run(scenario())


def test_pending_fill_race_never_requests_position_close(monkeypatch):
    async def scenario():
        control, _, proposal, payload, _ = await submitted(monkeypatch)
        await control.accept_bridge_heartbeat(payload, now=NOW)
        payload['positions'], payload['orders'] = payload['orders'], []
        result = await control.accept_bridge_heartbeat(payload, now=NOW)
        assert result['pending_entry_leases'] == ''
        assert await control.repository.pending_commands() == ()
        assert not (await control.repository.proposal(proposal['proposal_id']))[0].get('pending_cancellation_reason')
    asyncio.run(scenario())


@pytest.mark.parametrize('failure', ['old_ea','minimum_distance'])
def test_waiting_controls_survive_temporary_placement_block(monkeypatch, failure):
    async def scenario():
        control, _, p, _, _ = await prepare(monkeypatch, capability=failure!='old_ea', minimum='1000' if failure=='minimum_distance' else '0')
        await control.validate_proposal_publication(p, now=NOW)
        with pytest.raises(FTMOMasterError, match='EA 1.21|minimum distance'):
            await control.approve(p['proposal_id'], '42', now=NOW)
        assert (await control.repository.proposal(p['proposal_id']))[0]['status'] == 'pending_confirmation'
        assert await control.repository.pending_commands() == ()
    asyncio.run(scenario())


def test_market_preview_becomes_pending_without_moving_approved_levels(monkeypatch):
    async def scenario():
        control, _, p, payload, _ = await prepare(monkeypatch, price='100')
        assert p['order_type'] == 'market'
        payload['quotes']['AAPL'].update(bid='104.98', ask='105')
        await control.accept_bridge_heartbeat(payload, now=NOW)
        await control.validate_proposal_publication(p, now=NOW)
        cmd = await control.approve(p['proposal_id'], '42', now=NOW)
        assert cmd['payload']['order_type'] == 'limit'
        assert cmd['payload']['entry'] == p['planned_entry']
        assert cmd['payload']['stop_loss'] == p['stop_loss'] and cmd['payload']['take_profit'] == p['take_profit']
    asyncio.run(scenario())


def test_pending_approval_never_upgrades_to_market_or_increases_risk(monkeypatch):
    async def scenario():
        control, _, p, payload, _ = await prepare(monkeypatch)
        payload['quotes']['AAPL'].update(bid='100.48', ask='100.50')
        payload.update(equity='10100')
        await control.accept_bridge_heartbeat(payload, now=NOW)
        cmd = await control.approve(p['proposal_id'], '42', now=NOW)
        assert cmd['payload']['order_type'] == 'limit' and cmd['payload']['entry'] == p['entry']
        assert Decimal(cmd['risk_policy']['actual_risk_amount']) <= Decimal(p['risk_amount'])
    asyncio.run(scenario())


def test_reject_waiting_setup_creates_no_order(monkeypatch):
    async def scenario():
        control, _, p, _, _ = await prepare(monkeypatch)
        await control.reject(p['proposal_id'], '42')
        with pytest.raises(FTMOMasterError): await control.approve(p['proposal_id'], '42', now=NOW)
        assert await control.repository.pending_commands() == ()
    asyncio.run(scenario())


def test_policy_blocks_market_outside_zone_and_preserves_inputs():
    values = dict(side='sell', planned=Decimal('100'), executable=Decimal('105'), low=Decimal('99'), high=Decimal('101'))
    before = dict(values)
    assert entry_order_type(**values) == 'stop'
    assert values == before


@pytest.mark.parametrize('stage', ['approval', 'delivery'])
def test_signal_invalidation_blocks_entry_at_each_boundary(monkeypatch, stage):
    async def scenario():
        control, store, p, _, _ = await prepare(monkeypatch)
        if stage == 'delivery':
            await control.approve(p['proposal_id'], '42', now=NOW)
        await store.put(control.repository.SIGNALS, p['signal_id'], {'status': 'invalidated'})
        if stage == 'approval':
            with pytest.raises(FTMOMasterError, match='invalidated'):
                await control.approve(p['proposal_id'], '42', now=NOW)
        assert await control.commands_for_bridge(now=NOW) == ()
    asyncio.run(scenario())


def test_early_structural_invalidation_cancels_before_buffered_stop(monkeypatch):
    async def scenario():
        control, _, _, payload, kwargs = await prepare(monkeypatch)
        kwargs['signal_id'] = 'structural'
        kwargs['evidence_bundle']['evidence_bundle']['structural_invalidation'] = '95'
        kwargs['evidence_bundle']['structural_invalidation'] = '95'
        # The fixture store holds the same immutable test proof; production CAS
        # persists this bound level with the original hierarchy evidence.
        proposal = await control.create_signal_proposal(**kwargs)
        command = await control.approve(proposal['proposal_id'], '42', now=NOW)
        assert command['payload']['setup_invalidation_price'] == '95'
        assert command['payload']['stop_loss'] == '90'
        await control.commands_for_bridge(now=NOW)
        payload['orders'] = [dict(ticket='7799', symbol=proposal['symbol'], magic='26082501', type=2,
            comment='MNP:' + command['command_id'][:16], price_open=proposal['entry'], sl=proposal['stop_loss'],
            tp=proposal['take_profit'], volume=proposal['volume'], expiration_epoch=command['payload']['pending_native_expires_epoch'])]
        payload['quotes']['AAPL'].update(bid='94', ask='94.02')
        result = await control.accept_bridge_heartbeat(payload, now=NOW)
        assert result['pending_entry_leases'] == ''
        assert 'structural stop' in (await control.repository.proposal(proposal['proposal_id']))[0]['pending_cancellation_reason']
    asyncio.run(scenario())


def test_pending_lease_never_outlives_shortened_analysis_expiry(monkeypatch):
    async def scenario():
        control, _, p, payload, _ = await submitted(monkeypatch)
        await control.repository.update_telegram_analysis(p['analysis_id'], {'expires_at': (NOW + timedelta(seconds=8)).isoformat()})
        result = await control.accept_bridge_heartbeat(payload, now=NOW)
        stamp = str(int((NOW + timedelta(seconds=8)).timestamp()))
        assert result['pending_entry_leases'] == '7788|' + stamp + '|' + stamp
    asyncio.run(scenario())


def test_thirty_minute_broker_expiry_is_separate_from_freshness_and_never_renewed(monkeypatch):
    async def scenario():
        control, _, _, payload, kwargs = await prepare(monkeypatch, symbol='BTCUSD')
        kwargs.update(signal_id='thirty-minute', signal_expires_at=NOW + timedelta(hours=1))
        proposal = await control.create_signal_proposal(**kwargs)
        command = await control.approve(proposal['proposal_id'], '42', now=NOW)
        native = str(int((NOW + timedelta(minutes=30)).timestamp()))
        assert command['payload']['pending_native_expires_epoch'] == native
        assert command['payload']['pending_lease_epoch'] == str(int((NOW + timedelta(seconds=20)).timestamp()))
        assert command['expires_at'] == (NOW + timedelta(seconds=30)).isoformat()
        assert command['payload']['pending_entry_version'] == '2'
        await control.commands_for_bridge(now=NOW)
        payload['orders'] = [dict(ticket='7788', symbol=proposal['symbol'], magic='26082501', type=2,
            comment='MNP:' + command['command_id'][:16], price_open=proposal['entry'], sl=proposal['stop_loss'],
            tp=proposal['take_profit'], volume=proposal['volume'], expiration_epoch=native)]
        later = NOW + timedelta(seconds=10)
        payload['quotes']['BTCUSD']['timestamp'] = later.isoformat()
        result = await control.accept_bridge_heartbeat(payload, now=later)
        assert result['pending_entry_leases'] == f"7788|{int((later + timedelta(seconds=20)).timestamp())}|{native}"
        assert (await control.repository.command(command['command_id']))[0]['payload']['pending_native_expires_epoch'] == native
    asyncio.run(scenario())


def test_pending_native_expiry_respects_earlier_source_deadline_at_approval(monkeypatch):
    async def scenario():
        control, _, proposal, _, _ = await prepare(monkeypatch)
        deadline = NOW + timedelta(seconds=90)
        await control.repository.update_telegram_analysis(proposal['analysis_id'], {'expires_at': deadline.isoformat()})
        command = await control.approve(proposal['proposal_id'], '42', now=NOW)
        assert command['payload']['pending_native_expires_epoch'] == str(int(deadline.timestamp()))
    asyncio.run(scenario())


def test_heartbeat_pending_manifest_is_signed_and_bound_to_request_nonce():
    from datetime import datetime, timezone
    from types import SimpleNamespace
    import base64
    import hashlib
    import hmac
    import json
    import secrets
    from monatise.application.production import ProductionASGI
    from monatise.application.ftmo_master import FTMOBridgeAuthenticator
    async def scenario():
        now = datetime.now(timezone.utc)
        control, _ = service()
        payload = heartbeat()
        payload['quotes']['XAUUSD']['timestamp'] = now.isoformat()
        body = json.dumps(payload).encode()
        nonce, stamp = secrets.token_hex(16), str(int(now.timestamp()))
        path = '/api/ftmo/bridge/heartbeat'
        signature = FTMOBridgeAuthenticator.sign(control.configuration.bridge_secret, 'POST', path, stamp, nonce, body)
        scope = {'method': 'POST', 'path': path, 'headers': [(b'x-monatise-timestamp', stamp.encode()), (b'x-monatise-nonce', nonce.encode()), (b'x-monatise-signature', signature.encode())]}
        async def receive(): return {'type': 'http.request', 'body': body, 'more_body': False}
        app = ProductionASGI(SimpleNamespace(ftmo_master=control))
        code, result = await app._ftmo_bridge_request(scope, receive)
        assert code == 200 and 'pending_entry_leases' not in result
        serialized = base64.b64decode(result['pending_manifest'])
        manifest = json.loads(serialized)
        assert manifest['nonce'] == nonce and manifest['account'] == '12345678' and manifest['leases'] == ''
        assert hmac.compare_digest(result['pending_manifest_signature'], hmac.new(control.configuration.bridge_secret.encode(), serialized, hashlib.sha256).hexdigest())
        assert (await app._ftmo_bridge_request(scope, receive))[0] == 401
    asyncio.run(scenario())


def test_working_pending_order_remains_valid_as_price_reaches_entry(monkeypatch):
    async def scenario():
        control, _, _, payload, _ = await submitted(monkeypatch)
        payload['quotes']['AAPL'].update(bid='99.99', ask='100', stops_level='50')
        result = await control.accept_bridge_heartbeat(payload, now=NOW)
        assert result['pending_entry_leases'].startswith('7788|')
    asyncio.run(scenario())


@pytest.mark.parametrize('price,kind', [('105','limit'), ('95','stop')])
@pytest.mark.parametrize('boundary', ['delivery', 'ea'])
def test_late_price_refusal_offers_fixed_pending_entry_with_fresh_approval(monkeypatch, price, kind, boundary):
    async def scenario():
        control, _, original, payload, _ = await prepare(monkeypatch, price='100')
        command = await control.approve(original['proposal_id'], '42', now=NOW)
        if boundary == 'ea':
            await control.commands_for_bridge(now=NOW)
        payload['quotes']['AAPL'].update(ask=price, bid=str(Decimal(price) - Decimal('.02')))
        await control.accept_bridge_heartbeat(payload, now=NOW)
        if boundary == 'ea':
            ack = await control.acknowledge(command['command_id'], {'status':'rejected','submission_attempted':False,
                'message':'live FTMO price exceeded the approved deviation'})
            assert ack['limit_replacement_eligible']
        else:
            assert await control.commands_for_bridge(now=NOW) == ()
        child = await control.create_limit_replacement(original['proposal_id'], actor='42', now=NOW)
        assert child['order_type'] == kind and child['pending_only']
        assert child['entry'] == original['planned_entry']
        assert child['stop_loss'] == original['stop_loss'] and child['take_profit'] == original['take_profit']
        assert child['expires_at'] == original['expires_at']
        assert Decimal(child['risk_amount']) <= Decimal(original['risk_amount'])
        assert child['entry_policy'] == 'fixed_zone_v1'
        assert await control.repository.pending_commands() == ()
        notifier = TelegramNotifier(Transport(), '42', proposal_service=control)
        await notifier.trade_proposal('pending preview', child['proposal_id'])
        saved = (await control.repository.proposal(child['proposal_id']))[0]
        assert saved['approval_keyboard_attached']
        child_command = await control.approve(child['proposal_id'], '42', now=NOW)
        assert child_command['command_id'] != command['command_id']
        assert child_command['payload']['pending_entry_version'] == '2'
        assert child_command['payload']['order_type'] == kind
    asyncio.run(scenario())


@pytest.mark.parametrize('mutate', [{'submission_attempted':True}, {'status':'broker_uncertain'}, {'broker_ticket':'777'}, {'broker_retcode':'10020'}])
def test_managed_entry_never_reoffers_uncertain_submission(monkeypatch, mutate):
    async def scenario():
        control, _, original, payload, _ = await prepare(monkeypatch, price='100')
        command = await control.approve(original['proposal_id'], '42', now=NOW)
        await control.commands_for_bridge(now=NOW)
        await control.acknowledge(command['command_id'], {'status':'rejected','submission_attempted':False,
            'message':'live FTMO price exceeded the approved deviation', **mutate})
        payload['quotes']['AAPL'].update(bid='104.98', ask='105')
        await control.accept_bridge_heartbeat(payload, now=NOW)
        assert await control.create_limit_replacement(original['proposal_id'], actor='42', now=NOW) is None
    asyncio.run(scenario())

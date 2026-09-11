from __future__ import annotations

import asyncio
import copy
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

import monatise.application.ftmo_master as master_module
from monatise.application.deployment import TelegramNotificationTransport
from monatise.application.ftmo_master import FTMOMasterError
from monatise.application.production import ProductionASGI
from monatise.application.trade_publication import CONTEXT_ONLY
from monatise.application.workflows import TelegramNotifier
from tests.test_ftmo_master import NOW, active_environment, heartbeat, service


SYMBOLS = [('XAU/USD', 'XAUUSD'), ('US100.cash', 'US100.CASH'), ('US500.cash', 'US500.CASH')]


class Transport:
    def __init__(self):
        self.messages, self.proposals, self.retractions = [], [], []
        self.retry_controls = []

    async def send_message(self, chat, text):
        self.messages.append((chat, text))
        return 700 + len(self.messages)

    async def send_trade_proposal(self, chat, text, proposal_id):
        self.proposals.append((chat, text, proposal_id))
        return 800 + len(self.proposals)

    async def update_trade_proposal(self, chat, message_id, text, *, proposal_id=None):
        self.retractions.append((chat, message_id, text))
        self.retry_controls.append(proposal_id)
        return True


async def setup(monkeypatch, broker='XAUUSD', **environment):
    monkeypatch.setattr(master_module, '_utc', lambda value=None: value or NOW)
    control, store = service(active_environment(FTMO_TEMPORARY_ARM_REQUIRED='false', **environment))
    real_put = store.put
    async def durable_put(namespace, key, value, **options):
        return await real_put(namespace, key, copy.deepcopy(value), **options)
    store.put = durable_put
    quote = heartbeat()['quotes']['XAUUSD']
    await control.accept_bridge_heartbeat(heartbeat(quotes={broker: quote}), now=NOW)
    await control.repository.update_control(kill_switch=False)
    return control, store


async def proposal(control, symbol='XAUUSD', signal='signal-1', **kwargs):
    return await control.create_signal_proposal(
        signal_id=signal, analysis_id='analysis-' + signal, symbol=symbol, direction='LONG',
        analysis_entry='2500', analysis_stop='2490', analysis_target='2520',
        analysis_state='LONG', confirmation_status='confirmed', source='monatise.futures.scanner',
        now=NOW, **kwargs,
    )


@pytest.mark.parametrize('registry,broker', SYMBOLS)
def test_complete_symbol_proposal_publication_callback_and_bridge_handoff(monkeypatch, registry, broker):
    async def scenario():
        control, store = await setup(monkeypatch, broker)
        p = await proposal(control, registry)
        sent = []
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self):
                payload = sent[-1]
                return json.dumps({'ok': True, 'result': {'message_id': 901, 'reply_markup': payload['reply_markup']}}).encode()
        def request(req, timeout):
            sent.append(json.loads(req.data))
            # Durable sources and send intent must exist BEFORE Telegram sees anything.
            saved = store.values[(control.repository.PROPOSALS, p['proposal_id'])].value
            assert saved['telegram_publish_status'] == 'sending'
            assert (control.repository.ANALYSES, p['analysis_id']) in store.values
            assert (control.repository.SIGNALS, p['signal_id']) in store.values
            return Response()
        monkeypatch.setattr('monatise.application.deployment.urlopen', request)
        notifier = TelegramNotifier(TelegramNotificationTransport(lambda: 'test'), '42', proposal_service=control)
        assert await notifier.trade_proposal('caller text is not trusted', p['proposal_id']) == 901
        assert len(sent) == 1
        assert await notifier.trade_proposal('retry', p['proposal_id']) == 901
        assert len(sent) == 1
        buttons = sent[0]['reply_markup']['inline_keyboard'][0]
        assert [b['text'] for b in buttons] == ['✅ APPROVE TRADE', '❌ REJECT TRADE']
        assert [b['callback_data'] for b in buttons] == [f"ftmo:approve:{p['proposal_id']}", f"ftmo:reject:{p['proposal_id']}"]
        saved = (await control.repository.proposal(p['proposal_id']))[0]
        assert saved['symbol'] == broker and saved['telegram_message_id'] == 901
        assert saved['approval_keyboard_attached'] is True
        await control.validate_telegram_proposal(p['proposal_id'], actor='42', chat_id='42', message_id=901)
        assert await control.commands_for_bridge(now=NOW) == ()
        command = await control.approve(p['proposal_id'], '42', now=NOW)
        delivered = await control.commands_for_bridge(now=NOW)
        assert len(delivered) == 1 and delivered[0]['command_id'] == command['command_id']
        assert command['payload']['symbol'] == broker
        assert command['analysis_id'] == p['analysis_id'] and command['signal_id'] == p['signal_id']
        assert command['approval']['approved_by'] == '42'
        with pytest.raises(FTMOMasterError):
            await control.approve(p['proposal_id'], '42', now=NOW)
        assert len(await control.repository.pending_commands()) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('refresh_state', ['missing', 'stale', 'wrong_symbol', 'future', 'expired', 'kill_switch'])
def test_approval_refresh_still_requires_valid_quote_and_execution_gates(monkeypatch, refresh_state):
    async def scenario():
        control, store = await setup(monkeypatch, 'INTC', FTMO_APPROVAL_QUOTE_WAIT_SECONDS='1')
        clock = [NOW.replace(hour=15)]
        monkeypatch.setattr(master_module, '_utc', lambda value=None: value or clock[0])
        quote = dict(heartbeat()['quotes']['XAUUSD'], timestamp=clock[0].isoformat())
        await control.accept_bridge_heartbeat(heartbeat(quotes={'INTC': quote}), now=clock[0])
        p = await control.create_trade_proposal(
            actor='42', symbol='INTC', side='buy', order_type='market',
            stop_loss='2490.20', take_profit='2520.20',
        )
        clock[0] += timedelta(seconds=20)
        await control.accept_bridge_heartbeat(heartbeat(quotes={}), now=clock[0])

        async def refresh():
            async with asyncio.timeout(0.8):
                while 'INTC' not in await control.requested_execution_quote_symbols():
                    await asyncio.sleep(0.01)
            if refresh_state == 'expired':
                clock[0] += timedelta(days=1)
            if refresh_state == 'kill_switch':
                await control.repository.update_control(kill_switch=True)
            tick_at = clock[0] + timedelta(seconds=10 if refresh_state == 'future' else -20 if refresh_state == 'stale' else 0)
            fresh = dict(quote, timestamp=tick_at.isoformat())
            quotes = {} if refresh_state == 'missing' else {'AAPL' if refresh_state == 'wrong_symbol' else 'INTC': fresh}
            await control.accept_bridge_heartbeat(heartbeat(quotes=quotes), now=clock[0])

        task = asyncio.create_task(refresh())
        try:
            with pytest.raises(FTMOMasterError):
                await control.approve(p['proposal_id'], '42')
            await task
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        assert await control.repository.pending_commands() == ()
        assert (await control.repository.proposal(p['proposal_id']))[0].get('command_id') is None
        if refresh_state in {'missing', 'stale', 'wrong_symbol'}:
            event = next(e for e in store.streams[control.repository.AUDIT] if e['event'] == 'approval_quote_refresh_failed')
            assert event['fields']['refresh_requested'] is True
            assert event['fields']['quote_present'] is (refresh_state == 'stale')
    asyncio.run(scenario())


@pytest.mark.parametrize('blocked_by', ['unauthorized', 'expired', 'rejected', 'disabled', 'deterministic'])
def test_ineligible_approval_does_not_request_dynamic_quotes(monkeypatch, blocked_by):
    async def scenario():
        control, _ = await setup(monkeypatch)
        p = await proposal(control)
        if blocked_by == 'rejected':
            await control.reject(p['proposal_id'], '42')
        if blocked_by == 'disabled':
            await control.repository.update_control(kill_switch=True)
        current = NOW + timedelta(days=1) if blocked_by == 'expired' else NOW
        monkeypatch.setattr(master_module, '_utc', lambda value=None: value or current)
        await control.accept_bridge_heartbeat(heartbeat(quotes={}), now=current)
        with pytest.raises(FTMOMasterError):
            await control.approve(p['proposal_id'], 'wrong-user' if blocked_by == 'unauthorized' else '42',
                                  **({'now': current} if blocked_by == 'deterministic' else {}))
        assert await control.requested_execution_quote_symbols() == ()
        assert await control.repository.pending_commands() == ()
    asyncio.run(scenario())


def test_context_notification_is_explicit_and_has_no_controls():
    async def scenario():
        transport = Transport()
        notifier = TelegramNotifier(transport, '42')
        await notifier.ftmo_futures_notification('Qualified analysis; quote unavailable')
        assert CONTEXT_ONLY in transport.messages[0][1]
        assert 'approval_controls_omitted_reason=' in transport.messages[0][1]
        assert transport.proposals == []
    asyncio.run(scenario())


@pytest.mark.parametrize('symbol', ['INTC', 'AAPL', 'US500.cash'])
@pytest.mark.parametrize('quote_state', ['missing', 'stale'])
def test_approval_resubscribes_after_scanner_quote_demand_expires(monkeypatch, symbol, quote_state):
    async def scenario():
        control, _ = await setup(monkeypatch, symbol, FTMO_APPROVAL_QUOTE_WAIT_SECONDS='2')
        clock = [NOW.replace(hour=15)]
        monkeypatch.setattr(master_module, '_utc', lambda value=None: value or clock[0])
        quote = dict(heartbeat()['quotes']['XAUUSD'], timestamp=clock[0].isoformat())
        await control.request_execution_quote(symbol, lifetime_seconds=10)
        await control.accept_bridge_heartbeat(heartbeat(quotes={symbol: quote}), now=clock[0])
        p = await control.create_signal_proposal(
            signal_id='delayed-approval', analysis_id='delayed-analysis', symbol=symbol,
            direction='LONG', analysis_entry='2500', analysis_stop='2490', analysis_target='2520',
            analysis_state='LONG', confirmation_status='confirmed', source='monatise.stock.scanner',
        )
        notifier = TelegramNotifier(Transport(), '42', proposal_service=control)
        message_id = await notifier.trade_proposal('preview', p['proposal_id'])
        clock[0] += timedelta(seconds=20)
        assert await control.requested_execution_quote_symbols() == ()
        quotes = {} if quote_state == 'missing' else {symbol: quote}
        await control.accept_bridge_heartbeat(heartbeat(quotes=quotes), now=clock[0])
        assert await control.commands_for_bridge(now=clock[0]) == ()

        async def bridge_responds_only_to_demand():
            # Model the EA: heartbeat response advertises requested symbols;
            # only then can the next heartbeat report that instrument again.
            async with asyncio.timeout(1):
                while symbol not in await control.requested_execution_quote_symbols():
                    await asyncio.sleep(0.01)
            fresh = dict(quote, bid='2501.00', ask='2501.20', timestamp=clock[0].isoformat())
            await control.accept_bridge_heartbeat(heartbeat(quotes={symbol: fresh}), now=clock[0])

        refresh = asyncio.create_task(bridge_responds_only_to_demand())
        app = ProductionASGI(SimpleNamespace(ftmo_master=control, telegram=notifier))
        app._telegram_command_context = {
            'user_id': '42', 'chat_id': '42', 'chat_type': 'private',
            'message_id': message_id, 'callback_query_id': 'delayed-callback',
        }
        try:
            await app._handle_ftmo_telegram_command('/approve ' + p['proposal_id'])
            await refresh
        finally:
            if not refresh.done():
                refresh.cancel()
            await asyncio.gather(refresh, return_exceptions=True)
        saved = (await control.repository.proposal(p['proposal_id']))[0]
        assert saved['status'] == 'command_created'
        commands = await control.commands_for_bridge(now=clock[0])
        assert len(commands) == 1
        assert commands[0]['execution_snapshot']['ftmo_ask'] == '2501.20'
        assert commands[0]['approval']['approved_by'] == '42'
        with pytest.raises(FTMOMasterError, match='already'):
            await control.approve(p['proposal_id'], '42')
        assert len(await control.repository.pending_commands()) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('failure', ['missing', 'stale', 'future', 'mapping'])
def test_invalid_mt5_quote_cannot_create_proposal(monkeypatch, failure):
    async def scenario():
        control, store = await setup(monkeypatch)
        h = heartbeat()
        if failure in {'missing', 'mapping'}:
            h['quotes'] = {} if failure == 'missing' else {'EURUSD': h['quotes']['XAUUSD']}
        else:
            h['quotes']['XAUUSD']['timestamp'] = (NOW + timedelta(seconds=-6 if failure == 'stale' else 6)).isoformat()
        await control.accept_bridge_heartbeat(h, now=NOW)
        with pytest.raises(FTMOMasterError):
            await proposal(control)
        assert await control.repository.proposals() == ()
    asyncio.run(scenario())


@pytest.mark.parametrize('failure', ['proposal', 'analysis', 'signal', 'send_intent'])
def test_persistence_failure_prevents_executable_publication(monkeypatch, failure):
    async def scenario():
        control, store = await setup(monkeypatch)
        real_put = store.put
        namespace = {'proposal':control.repository.PROPOSALS, 'analysis':control.repository.ANALYSES,
                     'signal':control.repository.SIGNALS,'send_intent':control.repository.PROPOSALS}[failure]
        async def fail(ns, key, value, **options):
            if ns == namespace and (failure != 'send_intent' or value.get('telegram_publish_status') == 'sending'):
                raise RuntimeError('persistence unavailable')
            return await real_put(ns,key,value,**options)
        store.put = fail
        transport = Transport()
        notifier = TelegramNotifier(transport, '42', proposal_service=control)
        with pytest.raises(RuntimeError):
            p = await proposal(control)
            await notifier.trade_proposal('irrelevant',p['proposal_id'])
        assert transport.proposals == []
    asyncio.run(scenario())


def test_post_send_persistence_failure_retracts_controls_and_blocks_approval(monkeypatch):
    async def scenario():
        control, store = await setup(monkeypatch)
        p = await proposal(control)
        async def fail(*_): raise RuntimeError('DB unavailable')
        control.repository.attach_proposal_telegram_message = fail
        transport = Transport()
        notifier = TelegramNotifier(transport,'42',proposal_service=control)
        with pytest.raises(RuntimeError): await notifier.trade_proposal('proposal',p['proposal_id'])
        assert len(transport.proposals) == 1
        assert CONTEXT_ONLY in transport.retractions[0][2]
        with pytest.raises(FTMOMasterError): await control.approve(p['proposal_id'],'42',now=NOW)
        with pytest.raises(FTMOMasterError): await notifier.trade_proposal('retry',p['proposal_id'])
        assert len(transport.proposals) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('field,value', [('actor','43'),('chat_id','99'),('message_id',902)])
def test_wrong_callback_binding_is_rejected(monkeypatch,field,value):
    async def scenario():
        control,_ = await setup(monkeypatch)
        p = await proposal(control)
        notifier=TelegramNotifier(Transport(),'42',proposal_service=control)
        await notifier.trade_proposal('proposal',p['proposal_id'])
        args={'actor':'42','chat_id':'42','message_id':801};args[field]=value
        with pytest.raises(FTMOMasterError): await control.validate_telegram_proposal(p['proposal_id'],**args)
        assert await control.commands_for_bridge(now=NOW) == ()
    asyncio.run(scenario())


def test_rejection_wins_race_without_leaving_executable_command(monkeypatch):
    async def scenario():
        control, store = await setup(monkeypatch)
        p=await proposal(control)
        original=control.repository.update_proposal
        async def competing(pid,value,version):
            if value.get('lifecycle_state')=='APPROVAL_CLAIMED':
                await control.reject(pid,'42')
            await original(pid,value,version)
        control.repository.update_proposal=competing
        with pytest.raises(FTMOMasterError): await control.approve(p['proposal_id'],'42',now=NOW)
        assert (await control.repository.proposal(p['proposal_id']))[0]['status']=='rejected'
        assert await control.repository.pending_commands()==()
        assert await control.commands_for_bridge(now=NOW)==()
    asyncio.run(scenario())


def test_concurrent_approvals_create_exactly_one_command(monkeypatch):
    async def scenario():
        control, _ = await setup(monkeypatch)
        p=await proposal(control)
        results=await asyncio.gather(*(control.approve(p['proposal_id'],'42',now=NOW) for _ in range(2)),return_exceptions=True)
        assert sum(isinstance(x,dict) for x in results)==1
        assert len(await control.repository.pending_commands())==1
    asyncio.run(scenario())


@pytest.mark.parametrize('state',['rejected','expired','superseded','kill'])
def test_invalid_proposal_never_publishes_executable_controls(monkeypatch,state):
    async def scenario():
        control,_=await setup(monkeypatch)
        p=await proposal(control)
        if state=='rejected': await control.reject(p['proposal_id'],'42')
        elif state=='kill': await control.repository.update_control(kill_switch=True)
        else:
            value,version=await control.repository.proposal(p['proposal_id'])
            value.update({'expires_at':(NOW-timedelta(seconds=1)).isoformat()} if state=='expired' else {'superseded_by_signal_id':'next'})
            await control.repository.update_proposal(p['proposal_id'],value,version)
        transport=Transport();n=TelegramNotifier(transport,'42',proposal_service=control)
        await n.trade_proposal('proposal',p['proposal_id'])
        assert transport.proposals==[] and CONTEXT_ONLY in transport.messages[0][1]
        with pytest.raises(FTMOMasterError): await control.approve(p['proposal_id'],'42',now=NOW)
        assert await control.commands_for_bridge(now=NOW)==()
    asyncio.run(scenario())


def test_missing_keyboard_transport_never_falls_back_to_actionable_text(monkeypatch):
    async def scenario():
        control,_=await setup(monkeypatch);p=await proposal(control)
        t=Transport();t.send_trade_proposal=None
        await TelegramNotifier(t,'42',proposal_service=control).trade_proposal('proposal',p['proposal_id'])
        assert CONTEXT_ONLY in t.messages[0][1]
        assert 'APPROVAL_TRANSPORT_UNAVAILABLE' in t.messages[0][1]
        assert 'Approve: /approve' not in t.messages[0][1]
    asyncio.run(scenario())


def test_transport_refuses_actionable_plain_text():
    transport=TelegramNotificationTransport(lambda:'test')
    with pytest.raises(RuntimeError,match='both approval controls'):
        transport._send('42','Status: AWAITING APPROVAL')


@pytest.mark.parametrize('registry,broker',SYMBOLS)
@pytest.mark.parametrize('action',['approve','reject'])
def test_real_webhook_routes_callback_to_persisted_proposal(monkeypatch,registry,broker,action):
    from tests.test_production_entrypoint import Runtime, telegram_webhook
    from monatise.application.production import telegram_webhook_secret
    async def prepare():
        control,_=await setup(monkeypatch,broker)
        p=await proposal(control,registry)
        transport=Transport()
        notifier=TelegramNotifier(transport,'42',proposal_service=control)
        mid=await notifier.trade_proposal('proposal',p['proposal_id'])
        return control,p,notifier,transport,mid
    control,p,notifier,transport,mid=asyncio.run(prepare())
    runtime=Runtime();runtime.ftmo_master=control;runtime.telegram=notifier
    runtime.environment.update({'MONATISE_TELEGRAM_BOT_TOKEN':'test','MONATISE_TELEGRAM_CHAT_ID':'42'})
    app=ProductionASGI(runtime)
    update={'update_id':123,'callback_query':{'id':'callback123','from':{'id':42},
        'data':f"ftmo:{action}:{p['proposal_id']}",
        'message':{'message_id':mid,'chat':{'id':42,'type':'private'}}}}
    assert telegram_webhook(app,update,secret=telegram_webhook_secret('test'))==(200,{'status':'accepted'})
    assert telegram_webhook(app,update,secret=telegram_webhook_secret('test'))==(200,{'status':'duplicate'})
    saved=asyncio.run(control.repository.proposal(p['proposal_id']))[0]
    assert saved['status']==('command_created' if action=='approve' else 'rejected')
    assert transport.retractions[-1][1]==mid
    commands=asyncio.run(control.commands_for_bridge(now=NOW))
    assert len(commands)==(1 if action=='approve' else 0)


def test_telegram_response_missing_keyboard_is_retracted(monkeypatch):
    requests=[]
    class Response:
        status=200
        def __enter__(self): return self
        def __exit__(self,*_): pass
        def read(self): return b'{"ok":true,"result":{"message_id":123}}'
    def request(req,timeout): requests.append((req.full_url,json.loads(req.data)));return Response()
    monkeypatch.setattr('monatise.application.deployment.urlopen',request)
    with pytest.raises(RuntimeError):
        asyncio.run(TelegramNotificationTransport(lambda:'test').send_trade_proposal('42','proposal','a1b2c3d4e5f6'))
    assert requests[-1][0].endswith('/editMessageText')
    assert requests[-1][1]['reply_markup']=={'inline_keyboard':[]}
    assert CONTEXT_ONLY in requests[-1][1]['text']


def test_half_committed_approval_never_reaches_bridge(monkeypatch):
    async def scenario():
        control,_=await setup(monkeypatch);p=await proposal(control)
        original=control.repository.update_proposal
        async def fail_final(pid,value,version):
            if value.get('lifecycle_state')=='EXECUTION_QUEUED': raise RuntimeError('DB outage after command write')
            await original(pid,value,version)
        control.repository.update_proposal=fail_final
        with pytest.raises(RuntimeError): await control.approve(p['proposal_id'],'42',now=NOW)
        assert len(await control.repository.pending_commands())==1
        assert await control.commands_for_bridge(now=NOW)==()
    asyncio.run(scenario())


@pytest.mark.parametrize('state,action', [
    ('qualified', 'approve'), ('qualified', 'reject'),
    ('stale_quote', None), ('unqualified', None),
])
def test_stock_universe_scanner_publishes_bound_controls_only_for_executable_proposals(monkeypatch, state, action):
    from monatise.application.deployment import OrchestrationRuntime
    from monatise.application.ftmo_registry import FTMO_REGISTRY
    from monatise.application.stock_universe import StockUniverseConfiguration
    from tests.test_stock_universe import Redis, snapshot

    async def scenario():
        control, _ = await setup(monkeypatch, 'AAPL')
        market_time = NOW.replace(hour=15)
        monkeypatch.setattr(master_module, '_utc', lambda value=None: value or market_time)
        quote = dict(heartbeat()['quotes']['XAUUSD'], bid='200.00', ask='200.20',
                     timestamp=(market_time - timedelta(seconds=6 if state == 'stale_quote' else 0)).isoformat())
        await control.accept_bridge_heartbeat(heartbeat(quotes={'AAPL': quote}), now=market_time)
        requests = []

        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self):
                payload = requests[-1]
                return json.dumps({'ok': True, 'result': {
                    'message_id': len(requests), **({'reply_markup': payload['reply_markup']} if 'reply_markup' in payload else {}),
                }}).encode()

        def request(req, timeout):
            requests.append(json.loads(req.data))
            return Response()

        class Alpaca:
            def stock_snapshots(self, symbols):
                assert symbols == ('AAPL',)
                return {'AAPL': snapshot(200, 195, bid=199.95, ask=200.05)}

        instrument = FTMO_REGISTRY.resolve('AAPL')
        registry = SimpleNamespace(for_asset_class=lambda _: (instrument,), resolve=FTMO_REGISTRY.resolve)
        runtime = OrchestrationRuntime(environment={'MONATISE_FTMO_SCANNER_QUOTE_WAIT_SECONDS': '0'})
        runtime.ftmo_master, runtime.ftmo_registry = control, registry
        runtime.alpaca, runtime.redis = Alpaca(), Redis()
        runtime.telegram = TelegramNotifier(TelegramNotificationTransport(lambda: 'test'), '42', proposal_service=control)
        monkeypatch.setattr('monatise.application.deployment.urlopen', request)

        async def analyze(candidate, configuration, index):
            return {
                'asset': 'AAPL', 'company_name': 'Example stock', 'direction': 'LONG',
                'decision': 'BUY_WATCH', 'score': 8, 'score_threshold': 7,
                'setup_status': 'unconfirmed' if state == 'unqualified' else 'confirmed',
                'current_price': 200, 'entry': 200, 'stop_loss': 198, 'target': 204,
                'targets': [204], 'reward_risk': 2, 'additional_context': {},
                'analysis_provider': 'flashalpha', 'analysis_instrument': 'AAPL',
                'analysis_id': 'stock-analysis-test', 'publication_id': 'stock-signal-test',
                'as_of': market_time.isoformat(), 'execution': {'enabled': False},
            }

        runtime._analyze_market_stock = analyze
        result = await runtime._run_stock_universe_scan(StockUniverseConfiguration(), 3600, 'test')
        assert result['failures'] == []
        proposals = await control.repository.proposals()
        if state == 'unqualified':
            assert requests == [] and proposals == ()
            assert result['qualified_count'] == 0
            return
        assert requests[0]['text'].startswith(CONTEXT_ONLY)
        assert 'reply_markup' not in requests[0]
        if state == 'stale_quote':
            assert len(requests) == 1 and proposals == ()
            assert result['proposal_published_count'] == 0
            return
        assert result['failures'] == [] and result['proposal_published_count'] == 1
        assert len(proposals) == 1 and len(requests) == 2
        p = proposals[0]
        assert p['analysis_source'] == 'monatise.stock.scanner' and p['symbol'] == 'AAPL'
        assert p['telegram_message_id'] == 2 and p['approval_keyboard_attached']
        buttons = requests[1]['reply_markup']['inline_keyboard'][0]
        assert [b['text'] for b in buttons] == ['✅ APPROVE TRADE', '❌ REJECT TRADE']
        assert [b['callback_data'] for b in buttons] == [f"ftmo:approve:{p['proposal_id']}", f"ftmo:reject:{p['proposal_id']}"]
        assert await control.commands_for_bridge(now=market_time) == ()
        app = ProductionASGI(runtime)
        app._telegram_command_context = {'user_id': '42', 'chat_id': '42', 'chat_type': 'private',
                                         'message_id': 2, 'callback_query_id': 'stock-callback'}
        await app._handle_ftmo_telegram_command(f"/{action} {p['proposal_id']}")
        saved = (await control.repository.proposal(p['proposal_id']))[0]
        assert saved['status'] == ('command_created' if action == 'approve' else 'rejected')
        commands = await control.commands_for_bridge(now=market_time)
        assert len(commands) == (1 if action == 'approve' else 0)
        if commands:
            assert commands[0]['payload']['symbol'] == 'AAPL'
        assert requests[-1]['reply_markup'] == {'inline_keyboard': []}
        again = await runtime._run_stock_universe_scan(StockUniverseConfiguration(), 3600, 'test')
        assert again['proposal_published_count'] == 0
        assert len(await control.repository.proposals()) == 1

    asyncio.run(scenario())

import asyncio
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest

from monatise.application.trade_accounting import (
    ACCOUNTS, NOTIFICATIONS, TradeAccountingService, format_trade_result, reconstruct,
)
from monatise.application.production import ProductionASGI
from tests.test_ftmo_master import service, heartbeat, active_environment, NOW


def proposal():
    return dict(proposal_id='a'*12, kind='open_trade', approved_by='42', broker_ticket='9001',
                command_id='b'*64, symbol='XAUUSD', side='buy', volume='0.09',
                stop_loss='4271.14', take_profit='4459.63', lifecycle_state='POSITION_OPEN',
                position_snapshot={'identifier':'9001'}, analysis_id='analysis', signal_id='signal')


def deals(profit='168.30', commission='-0.27', swap='0', fee='0'):
    return [dict(deal_id='1', position_id='9001', order_id='9001', entry='in',
                 volume='0.09', price='4276.91', profit='0', commission=commission,
                 swap='0', fee='0', reason='EXPERT', time=NOW.isoformat()),
            dict(deal_id='2', position_id='9001', order_id='9002', entry='out',
                 volume='0.09', price='4295.61', profit=profit, commission=commission,
                 swap=swap, fee=fee, reason='SL', time=(NOW+timedelta(minutes=42,seconds=18)).isoformat())]


@pytest.mark.parametrize('profit,commission,swap,fee,net,label', [
    ('168.30','-0.27','0','0','167.76','PROFIT'),
    ('-152.02','-1.02','0','0','-154.06','LOSS'),
    ('0','0','0','0','0','BREAKEVEN'),
    ('2','-0.5','-0.75','-0.25','0.00','BREAKEVEN'),
    ('2','-0.5','-1','-0.5','-0.5','LOSS'),
])
def test_realized_result_includes_both_commissions_swap_and_fees(profit,commission,swap,fee,net,label):
    from decimal import Decimal
    result=reconstruct(proposal(),deals(profit,commission,swap,fee),position=None,currency='USD')
    assert Decimal(result['net_pnl'])==Decimal(net)
    assert result['result']==label
    text=format_trade_result(result)
    for required in ['CLOSED TRADE','NET REALIZED P/L','Gross P/L:','Commission:','Swap/financing:',
                     'Other deal fees:','Opened:','Closed:','Duration: 42m 18s','XAUUSD','BUY','9001']:
        assert required in text
    assert 'Unrealized' not in text and 'P/L %: unavailable' in text


def test_broker_profit_is_authoritative_even_when_prices_would_imply_something_else():
    rows=deals('12');rows[-1]['price']='1'
    result=reconstruct(proposal(),rows,position=None,currency='USD')
    assert result['net_pnl']=='11.46' and result['exit_price']=='1'


def test_multiple_partial_exits_keep_position_open_until_all_volume_reconciles():
    rows=deals('10');rows[-1]['volume']='0.03'
    partial=reconstruct(proposal(),rows,position={'volume':'0.06'},currency='USD')
    assert partial['state']=='PARTIAL_CLOSE' and partial['remaining_volume']=='0.06'
    assert 'POSITION STILL OPEN' in format_trade_result(partial)
    assert partial['closed_at'] is None
    rows.append(dict(rows[-1],deal_id='3',volume='0.03',profit='20',reason='EXPERT'))
    partial=reconstruct(proposal(),rows,position={'volume':'0.03'},currency='USD')
    assert partial['state']=='PARTIAL_CLOSE'
    rows.append(dict(rows[-1],deal_id='4',volume='0.03',profit='30',reason='TP'))
    final=reconstruct(proposal(),rows,position=None,currency='USD')
    assert final['state']=='CLOSED' and final['net_pnl']=='58.92' and final['close_reason']=='TP'


def test_disappearance_without_complete_history_is_not_a_final_trade_result():
    rows=deals();rows[-1]['volume']='0.03'
    with pytest.raises(ValueError,match='closing deal history incomplete'):
        reconstruct(proposal(),rows,position=None,currency='USD')
    with pytest.raises(ValueError,match='opening deal history'):
        reconstruct(proposal(),rows[1:],position=None,currency='USD')


@pytest.mark.parametrize('field',['profit','commission','swap','fee'])
def test_missing_broker_amount_is_unknown_not_zero(field):
    rows=deals();del rows[-1][field]
    with pytest.raises(ValueError,match='missing broker amount'):
        reconstruct(proposal(),rows,position=None,currency='USD')


def test_duplicate_deal_is_counted_once_and_conflicts_fail_closed():
    rows=deals()
    result=reconstruct(proposal(),rows+deepcopy(rows),position=None,currency='USD')
    assert result['net_pnl']=='167.76'
    with pytest.raises(ValueError,match='conflicting duplicate'):
        reconstruct(proposal(),rows+[dict(rows[-1],profit='999')],position=None,currency='USD')


def test_partial_snapshot_and_incomplete_coverage_cannot_emit_final_result():
    with pytest.raises(ValueError,match='live position'):
        reconstruct(proposal(),deals(),position={'volume':'0.09'},currency='USD')
    with pytest.raises(ValueError,match='history incomplete'):
        reconstruct(proposal(),deals(),position=None,currency='USD',coverage={'complete':False,'deal_count':2})


def test_telegram_close_is_bound_to_matching_broker_order_and_target():
    command={'operation':'close','status':'reconciled','broker_ticket':'9002','payload':{'target_id':'9001'}}
    result=reconstruct(proposal(),deals(),position=None,currency='USD',commands=(command,))
    assert result['close_reason']=='Telegram close'
    command['payload']['target_id']='another'
    assert reconstruct(proposal(),deals(),position=None,currency='USD',commands=(command,))['close_reason']=='SL'


class Notifier:
    def __init__(self, fail=False): self.messages=[];self.fail=fail
    async def command_response(self,message):
        self.messages.append(message)
        if self.fail: raise TimeoutError()
        return 123


async def accounting_fixture():
    master,store=service(active_environment())
    await master.repository.save_proposal(proposal())
    snap=heartbeat(deals=deals(),identity_match=True)
    return master,store,snap,TradeAccountingService(master)


def test_repeated_and_concurrent_heartbeats_publish_only_one_close():
    async def run():
        master,store,snap,accounting=await accounting_fixture();notifier=Notifier()
        await asyncio.gather(accounting.reconcile(snap,NOW),accounting.reconcile(snap,NOW))
        await asyncio.gather(accounting.publish_pending(notifier),accounting.publish_pending(notifier))
        await accounting.reconcile(snap,NOW+timedelta(seconds=2))
        await accounting.publish_pending(notifier)
        assert len(notifier.messages)==1
        events=await store.list_namespace(NOTIFICATIONS)
        assert len(events)==1 and events[0].value['status']=='published'
        assert events[0].value['telegram_message_id']==123
    asyncio.run(run())


def test_uncertain_telegram_send_is_not_retried_and_remains_auditable():
    async def run():
        _,store,snap,accounting=await accounting_fixture();notifier=Notifier(fail=True)
        await accounting.reconcile(snap,NOW)
        await accounting.publish_pending(notifier)
        await accounting.publish_pending(notifier)
        assert len(notifier.messages)==1
        assert (await store.list_namespace(NOTIFICATIONS))[0].value['status']=='outcome_unknown'
    asyncio.run(run())


def test_historical_baseline_does_not_resend_previous_close_notifications():
    async def run():
        _,store,snap,accounting=await accounting_fixture()
        await accounting.reconcile(snap,NOW,previously_closed=('a'*12,))
        await accounting.reconcile(snap,NOW+timedelta(seconds=2),previously_closed=('a'*12,))
        assert not await store.list_namespace(NOTIFICATIONS)
        assert (await store.list_namespace(ACCOUNTS))[0].value['result']['net_pnl']=='167.76'
    asyncio.run(run())


def test_mismatched_account_cannot_publish_a_result():
    async def run():
        _,store,snap,accounting=await accounting_fixture();snap['identity_match']=False
        await accounting.reconcile(snap,NOW)
        assert not await store.list_namespace(NOTIFICATIONS)
    asyncio.run(run())


def test_old_lifecycle_formatter_never_calls_floating_pnl_a_closed_trade():
    async def run():
        app=ProductionASGI.__new__(ProductionASGI); notifier=Notifier()
        app.runtime=SimpleNamespace(telegram=notifier)
        await app._notify_ftmo_lifecycle({'lifecycle_state':'POSITION_CLOSED','unrealized_profit':'-1.35'})
        assert notifier.messages==[]
    asyncio.run(run())


@pytest.mark.parametrize('operation,policy,label',[
    ('breakeven','', 'SL — breakeven management'),
    ('sl','STRUCTURE_TRAIL:observed', 'SL — trailing management'),
])
def test_stop_management_reason_does_not_replace_actual_net_result(operation,policy,label):
    rows=deals('0');rows[-1]['sl']='4276.91'
    command={'operation':operation,'management_policy':policy,'status':'reconciled',
             'payload':{'target_id':'9001','value':'4276.91'}}
    result=reconstruct(proposal(),rows,position=None,currency='USD',commands=(command,))
    assert result['close_reason']==label and result['result']=='LOSS' and result['net_pnl']=='-0.54'

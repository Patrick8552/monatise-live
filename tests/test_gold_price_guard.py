"""Gold allowance at publication, manual approval and the native MT5 guard."""
import asyncio
import shutil
import subprocess
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from monatise.application.ftmo_master import FTMOMasterError, format_proposal
from tests.test_ftmo_master import NOW, heartbeat
from tests.test_trade_publication import setup


async def gold_setup(monkeypatch, **environment):
    control, store = await setup(monkeypatch, FTMO_GOLD_MAXIMUM_ADVERSE_PRICE_DEVIATION='10', **environment)
    await quote(control, '2500.20')
    return control, store


async def quote(control, ask, **changes):
    payload = heartbeat(gold_price_guard_version=1, gold_maximum_adverse_price_deviation='10', **changes)
    payload['quotes']['XAUUSD'].update(ask=str(ask), bid=str(Decimal(ask)-Decimal('.20')))
    await control.accept_bridge_heartbeat(payload, now=NOW)


async def proposal(control, side='buy', **kwargs):
    return await control.create_trade_proposal(
        actor='42', symbol='XAUUSD', side=side, order_type='market',
        stop_loss='2470.20' if side == 'buy' else '2530',
        take_profit='2570.20' if side == 'buy' else '2430', now=NOW, **kwargs)


@pytest.mark.parametrize('side', ['buy', 'sell'])
@pytest.mark.parametrize('adverse', ['9.99', '10', '10.01', '-15'])
def test_approved_price_bound_is_directional_and_not_reanchored(monkeypatch, side, adverse):
    async def scenario():
        control, _ = await gold_setup(monkeypatch)
        p = await proposal(control, side)
        original = Decimal(p['entry'])
        new_entry = original + Decimal(adverse) * (1 if side == 'buy' else -1)
        await quote(control, new_entry if side == 'buy' else new_entry + Decimal('.20'))
        if Decimal(adverse) > 10:
            with pytest.raises(FTMOMasterError, match='tolerance'):
                await control.approve(p['proposal_id'], '42', now=NOW)
            assert await control.repository.pending_commands() == ()
            child = await control.create_limit_replacement(p['proposal_id'], actor='42', now=NOW)
            assert child['entry'] == p['entry'] and child['order_type'] == 'limit'
            assert 'price_guard' not in child
            return
        command = await control.approve(p['proposal_id'], '42', now=NOW)
        payload = command['payload']
        assert Decimal(payload['entry']) == new_entry
        assert Decimal(payload['price_guard_reference']) == original
        assert Decimal(payload['maximum_adverse_price_deviation']) == 10
        assert Decimal(payload['volume']) <= Decimal(p['volume'])
        worst = original + (10 if side == 'buy' else -10)
        worst_risk = abs(worst - Decimal(payload['stop_loss'])) * 100 * Decimal(payload['volume'])
        assert worst_risk <= Decimal(payload['approved_risk_budget']) <= 300
        assert await control.commands_for_bridge(now=NOW)
        with pytest.raises(FTMOMasterError):
            await control.approve(p['proposal_id'], '42', now=NOW)
        assert len(await control.repository.store.list_namespace(control.repository.COMMANDS)) == 1
    asyncio.run(scenario())


def test_publication_discloses_allowance_and_requires_compatible_bridge(monkeypatch):
    async def scenario():
        control, _ = await gold_setup(monkeypatch)
        p = await proposal(control, metadata={'price_guard': {'reference': '1'}})
        assert p['price_guard']['reference'] == '2500.20'
        text = format_proposal(p)
        assert '$10 per ounce' in text and '2500.20' in text and 'Broker market fills can slip' in text
        await control.validate_proposal_publication(p, now=NOW)
        await control.accept_bridge_heartbeat(heartbeat(), now=NOW)
        with pytest.raises(FTMOMasterError, match='matching server and MT5'):
            await control.validate_proposal_publication(p, now=NOW)
        with pytest.raises(FTMOMasterError, match='matching server and MT5'):
            await control.approve(p['proposal_id'], '42', now=NOW)
        assert await control.repository.pending_commands() == ()
    asyncio.run(scenario())


@pytest.mark.parametrize('change', ['lower_policy', 'higher_policy', 'lower_equity', 'zone', 'reward_risk', 'kill', 'expired'])
def test_allowance_does_not_override_approved_budget_or_other_gates(monkeypatch, change):
    async def scenario():
        control, _ = await gold_setup(monkeypatch)
        p = await proposal(control, risk_fraction_limit='.01', metadata={'entry_zone_high': '2502'} if change == 'zone' else {})
        if change == 'lower_policy':
            control.configuration = replace(control.configuration, gold_maximum_adverse_price_deviation=Decimal('5'))
        elif change == 'higher_policy':
            control.configuration = replace(control.configuration, gold_maximum_adverse_price_deviation=Decimal('20'))
        elif change == 'lower_equity':
            await quote(control, '2500.20', equity='9900')
        elif change == 'zone':
            await quote(control, '2503.20')
        elif change == 'reward_risk':
            control.configuration = replace(control.configuration, minimum_reward_risk=Decimal('2'))
            await quote(control, '2510.20')
        elif change == 'kill':
            await control.repository.update_control(kill_switch=True)
        elif change == 'expired':
            from datetime import timedelta
            with pytest.raises(FTMOMasterError, match='expired'):
                await control.approve(p['proposal_id'], '42', now=NOW+timedelta(minutes=30))
            return
        if change in {'lower_policy', 'zone', 'reward_risk', 'kill'}:
            with pytest.raises(FTMOMasterError):
                await control.approve(p['proposal_id'], '42', now=NOW)
            assert await control.repository.pending_commands() == ()
        else:
            command = await control.approve(p['proposal_id'], '42', now=NOW)
            assert command['payload']['maximum_adverse_price_deviation'] == '10'
            assert Decimal(command['payload']['approved_risk_budget']) <= 100
            assert Decimal(command['payload']['volume']) <= Decimal(p['volume'])
    asyncio.run(scenario())


def test_other_symbols_pending_orders_and_legacy_proposals_keep_their_policy(monkeypatch):
    async def scenario():
        control, _ = await setup(monkeypatch, 'AAPL', FTMO_GOLD_MAXIMUM_ADVERSE_PRICE_DEVIATION='10')
        p = await control.create_trade_proposal(actor='42', symbol='AAPL', side='buy', order_type='market', stop_loss='2470', take_profit='2570', now=NOW)
        assert 'price_guard' not in p
        control, _ = await gold_setup(monkeypatch)
        p = await control.create_trade_proposal(actor='42', symbol='XAUUSD', side='buy', order_type='limit', entry='2499', stop_loss='2470', take_profit='2570', now=NOW)
        assert 'price_guard' not in p
        control.configuration = replace(control.configuration, gold_maximum_adverse_price_deviation=Decimal(0))
        legacy = await proposal(control)
        control.configuration = replace(control.configuration, gold_maximum_adverse_price_deviation=Decimal(10))
        command = await control.approve(legacy['proposal_id'], '42', now=NOW)
        assert 'gold_price_guard_version' not in command['payload']
    asyncio.run(scenario())


def test_actual_native_gold_guard_boundaries_and_invalid_inputs(tmp_path):
    compiler = shutil.which('c++')
    if compiler is None:
        pytest.skip('C++ compiler unavailable')
    source = Path('mt5/Experts/MonatiseFTMOBridge.mq5').read_text()
    function = 'bool GoldPriceGuard(' + source.split('bool GoldPriceGuard(', 1)[1].split('\nbool FinalOrderValidation', 1)[0]
    cpp = tmp_path / 'gold.cpp'
    cpp.write_text(r'''
#include <string>
#include <map>
#include <cmath>
using string=std::string;
std::map<string,string> fields{{"gold_price_guard_version","1"},{"price_guard_reference","4300"},{"maximum_adverse_price_deviation","10"}};
double InpGoldMaximumAdversePriceDeviation=10;
string JsonString(string, string key) { return fields[key]; }
double StringToDouble(string s) { try { return std::stod(s); } catch(...) { return 0; } }
bool MathIsValidNumber(double n) { return std::isfinite(n); }
bool ResolveBrokerSymbol(string, string &symbol, string &) { symbol="XAUUSD"; return true; }
''' + function + r'''
int main() {
 string reason;
 if(!GoldPriceGuard("","XAUUSD","buy",4310,reason)) return 1;
 if(GoldPriceGuard("","XAUUSD","buy",4310.01,reason)) return 2;
 if(!GoldPriceGuard("","XAUUSD","buy",4280,reason)) return 3;
 if(!GoldPriceGuard("","XAUUSD","sell",4290,reason)) return 4;
 if(GoldPriceGuard("","XAUUSD","sell",4289.99,reason)) return 5;
 if(!GoldPriceGuard("","XAUUSD","sell",4320,reason)) return 6;
 if(GoldPriceGuard("","AAPL","buy",4300,reason)) return 7;
 if(GoldPriceGuard("","XAUUSD","other",4300,reason)) return 8;
 fields["maximum_adverse_price_deviation"]="11";
 if(GoldPriceGuard("","XAUUSD","buy",4300,reason)) return 9;
 fields["maximum_adverse_price_deviation"]="nan";
 if(GoldPriceGuard("","XAUUSD","buy",4300,reason)) return 10;
 fields["maximum_adverse_price_deviation"]="10";
 fields["price_guard_reference"]="nan";
 if(GoldPriceGuard("","XAUUSD","buy",4300,reason)) return 11;
 fields["price_guard_reference"]="4300";
 fields["gold_price_guard_version"]="2";
 if(GoldPriceGuard("","XAUUSD","buy",4300,reason)) return 12;
 return 0;
}
''')
    binary = tmp_path / 'gold'
    subprocess.run([compiler, '-std=c++17', str(cpp), '-o', str(binary)], check=True, capture_output=True)
    subprocess.run([str(binary)], check=True, capture_output=True)


def test_ea_refusal_replacement_preserves_preview_after_approval_repricing(monkeypatch):
    async def scenario():
        control, _ = await gold_setup(monkeypatch)
        p = await proposal(control)
        await quote(control, '2505.20')
        command = await control.approve(p['proposal_id'], '42', now=NOW)
        assert command['payload']['entry'] == '2505.20'
        await control.commands_for_bridge(now=NOW)
        from monatise.application.ftmo_master import EA_PRICE_TOLERANCE_REASON
        await control.acknowledge(command['command_id'], {
            'status': 'rejected', 'submission_attempted': False, 'message': EA_PRICE_TOLERANCE_REASON})
        await quote(control, '2511.20')
        child = await control.create_limit_replacement(p['proposal_id'], actor='42', now=NOW)
        assert child['entry'] == p['entry'] == '2500.20'
        await control.validate_proposal_publication(child, now=NOW)
        assert child['expires_at'] == p['expires_at']
    asyncio.run(scenario())


def test_native_final_validation_enforces_gold_risk_setup_and_legacy_deviation(tmp_path):
    compiler = shutil.which('c++')
    if compiler is None:
        pytest.skip('C++ compiler unavailable')
    source = Path('mt5/Experts/MonatiseFTMOBridge.mq5').read_text()
    functions = 'bool GoldPriceGuard(' + source.split('bool GoldPriceGuard(', 1)[1].split('\nbool ResolvePendingOrderExpiration', 1)[0]
    cpp = tmp_path / 'final.cpp'
    cpp.write_text(r'''
#include <string>
#include <map>
#include <cmath>
using string=std::string; using ulong=unsigned long; using datetime=long;
bool InpExecutionEnabled=true, InpMasterAccountApproved=true;
int InpMaximumOpenExposures=5, InpMaximumDeviationPoints=20, InpMaximumSpreadTicks=80, InpMagicNumber=123;
double InpGoldMaximumAdversePriceDeviation=10, InpRiskFraction=.03, InpDailyLossLimit=500, InpTotalLossLimit=1000, InpInitialAccountBalance=10000;
enum {ORDER_MAGIC,POSITION_MAGIC,SYMBOL_TRADE_TICK_SIZE,SYMBOL_TRADE_TICK_VALUE_LOSS,SYMBOL_TRADE_TICK_VALUE,SYMBOL_POINT,SYMBOL_VOLUME_MIN,SYMBOL_VOLUME_MAX,SYMBOL_VOLUME_STEP,SYMBOL_TRADE_MODE,SYMBOL_TRADE_MODE_FULL,SYMBOL_TRADE_STOPS_LEVEL,SYMBOL_TRADE_FREEZE_LEVEL,ACCOUNT_EQUITY};
std::map<string,string> f{{"gold_price_guard_version","1"},{"price_guard_reference","4300"},{"maximum_adverse_price_deviation","10"},{"operation","open"},{"expires_epoch","2000"},{"symbol","XAUUSD"},{"side","buy"},{"order_type","market"},{"entry","4300"},{"volume",".02"},{"stop_loss","4270"},{"take_profit","4370"},{"approved_risk_budget","100"},{"minimum_reward_risk","1.5"}};
string JsonString(string, string k) { return f[k]; }
double StringToDouble(string s) { try {return std::stod(s);} catch(...) {return 0;} }
long StringToInteger(string s) { return (long)StringToDouble(s); }
bool MathIsValidNumber(double n) { return std::isfinite(n); }
double MathAbs(double n) { return std::abs(n); }
double MathRound(double n) { return std::round(n); }
double MathMax(double a,double b) { return std::fmax(a,b); }
double MathMin(double a,double b) { return std::fmin(a,b); }
bool ResolveBrokerSymbol(string, string &s, string &) {s="XAUUSD";return true;}
bool IdentityMatches() {return true;} bool TradingPermission() {return true;}
bool OrderSelect(ulong) {return false;} bool PositionSelectByTicket(ulong) {return false;}
long OrderGetInteger(int) {return 123;} long PositionGetInteger(int) {return 123;}
int PositionsTotal() {return 0;} int OrdersTotal() {return 0;}
datetime TimeGMT() {return 1000;} datetime BrokerTimeToUtc(datetime d) {return d;}
struct MqlTick {double ask=4310,bid=4309.8; datetime time=1000;};
double ask=4310;
bool SymbolInfoTick(string, MqlTick &t) {t.ask=ask;t.bid=ask-.2;return true;}
double SymbolInfoDouble(string,int k) {return k==SYMBOL_VOLUME_MAX?100:k==SYMBOL_TRADE_TICK_VALUE_LOSS||k==SYMBOL_TRADE_TICK_VALUE?1:.01;}
long SymbolInfoInteger(string,int k) {return k==SYMBOL_TRADE_MODE?SYMBOL_TRADE_MODE_FULL:5;}
double AccountInfoDouble(int) {return 10000;} double DailyStartEquity() {return 10000;}
bool CurrentOpenRisk(double &risk,string &) {risk=0;return true;}
''' + functions + r'''
int main() {
 string reason; double validated=0;
 if(!FinalOrderValidation("",reason,validated) || validated!=4310) return 1;
 ask=4310.01; if(FinalOrderValidation("",reason,validated)) return 2;
 ask=4310; f["approved_risk_budget"]="79"; if(FinalOrderValidation("",reason,validated)) return 3;
 f["approved_risk_budget"]="100"; f["minimum_reward_risk"]="1.51"; if(FinalOrderValidation("",reason,validated)) return 4;
 f["minimum_reward_risk"]="1.5"; f["entry_zone_high"]="4309"; if(FinalOrderValidation("",reason,validated)) return 5;
 f["entry_zone_high"]=""; f["volume"]=".03"; if(FinalOrderValidation("",reason,validated)) return 6;
 f["volume"]=".02"; f["approved_risk_budget"]="nan"; if(FinalOrderValidation("",reason,validated)) return 7;
 f["approved_risk_budget"]="100"; f["symbol"]="AAPL"; if(FinalOrderValidation("",reason,validated)) return 8;
 f["gold_price_guard_version"]=""; ask=4300.21; if(FinalOrderValidation("",reason,validated)) return 9;
 ask=4300.19; if(!FinalOrderValidation("",reason,validated)) return 10;
 f["expires_epoch"]="999"; if(FinalOrderValidation("",reason,validated)) return 11;
 return 0;
}
''')
    binary = tmp_path / 'final'
    subprocess.run([compiler, '-std=c++17', str(cpp), '-o', str(binary)], check=True, capture_output=True)
    subprocess.run([str(binary)], check=True, capture_output=True)

import asyncio
import shutil
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest

from monatise.application.ftmo_master import FTMOMasterError
from tests.test_ftmo_master import NOW, heartbeat
from tests.test_trade_publication import setup


@pytest.mark.parametrize('pending_risk', ['within_budget', 'exceeds_total', 'missing_stop', 'missing_quote'])
def test_pending_orders_reserve_risk_before_another_proposal(monkeypatch, pending_risk):
    async def scenario():
        control, _ = await setup(monkeypatch, FTMO_MAXIMUM_OPEN_EXPOSURES='5')
        payload = heartbeat(orders=[{
            'ticket': '999', 'symbol': 'US500.CASH', 'price_open': '2500', 'volume': '0.20',
            'sl': '0' if pending_risk == 'missing_stop' else '2490', 'tp': '2520',
        }])
        if pending_risk != 'missing_quote':
            payload['quotes']['US500.CASH'] = dict(payload['quotes']['XAUUSD'])
        await control.accept_bridge_heartbeat(payload, now=NOW)
        arguments = dict(actor='42', symbol='XAUUSD', side='buy', order_type='limit', entry='2499',
                         stop_loss='2489', take_profit='2519', risk_fraction_limit='.005' if pending_risk == 'within_budget' else '.03', now=NOW)
        if pending_risk == 'within_budget':
            proposal = await control.create_trade_proposal(**arguments)
            assert Decimal(proposal['risk_amount']) == Decimal('50')
        else:
            with pytest.raises(FTMOMasterError, match={'exceeds_total': 'total open risk', 'missing_stop': 'protective stop', 'missing_quote': 'cannot be priced'}[pending_risk]):
                await control.create_trade_proposal(**arguments)
        assert await control.repository.pending_commands() == ()
    asyncio.run(scenario())


def test_actual_ea_risk_calculation_counts_positions_and_pending_orders(tmp_path):
    compiler = shutil.which('c++')
    if compiler is None:
        pytest.skip('C++ compiler unavailable')
    bridge = Path('mt5/Experts/MonatiseFTMOBridge.mq5').read_text()
    function = 'bool CurrentOpenRisk(' + bridge.split('bool CurrentOpenRisk(', 1)[1].split('\nbool CsvContainsSymbol', 1)[0]
    source = tmp_path / 'risk.cpp'
    source.write_text(r'''
#include <string>
#include <vector>
#include <cmath>
using string = std::string;
using ulong = unsigned long;
struct Exposure { double entry, stop, volume; };
std::vector<Exposure> positions{{2500,2490,.10}}, orders{{2500,2490,.20}};
int selected_position, selected_order;
bool invalid_spec = false;
enum {POSITION_SYMBOL, ORDER_SYMBOL, POSITION_SL, ORDER_SL, POSITION_PRICE_OPEN,
      ORDER_PRICE_OPEN, POSITION_VOLUME, ORDER_VOLUME_CURRENT, SYMBOL_TRADE_TICK_SIZE,
      SYMBOL_TRADE_TICK_VALUE_LOSS, SYMBOL_TRADE_TICK_VALUE};
int PositionsTotal() { return positions.size(); }
int OrdersTotal() { return orders.size(); }
unsigned long PositionGetTicket(int i) { selected_position=i; return i+1; }
unsigned long OrderGetTicket(int i) { selected_order=i; return i+1; }
string PositionGetString(int) { return "XAUUSD"; }
string OrderGetString(int) { return "US500.CASH"; }
double PositionGetDouble(int key) { auto p=positions[selected_position]; return key==POSITION_SL?p.stop:key==POSITION_PRICE_OPEN?p.entry:p.volume; }
double OrderGetDouble(int key) { auto p=orders[selected_order]; return key==ORDER_SL?p.stop:key==ORDER_PRICE_OPEN?p.entry:p.volume; }
double SymbolInfoDouble(string symbol,int key) { return invalid_spec && symbol=="US500.CASH"?0:key==SYMBOL_TRADE_TICK_SIZE?.01:1; }
double MathAbs(double value) { return std::abs(value); }
''' + function + r'''
int main() {
 double risk=0; string reason;
 if(!CurrentOpenRisk(risk,reason) || std::abs(risk-300)>1e-8) return 1;
 orders[0].stop=0;
 if(CurrentOpenRisk(risk,reason)) return 2;
 orders[0].stop=2490; invalid_spec=true;
 if(CurrentOpenRisk(risk,reason)) return 3;
 invalid_spec=false; positions.clear();
 if(!CurrentOpenRisk(risk,reason) || std::abs(risk-200)>1e-8) return 4;
 orders.clear();
 if(!CurrentOpenRisk(risk,reason) || risk!=0) return 5;
 return 0;
}
''')
    binary = tmp_path / 'risk'
    subprocess.run([compiler, '-std=c++17', str(source), '-o', str(binary)], check=True, capture_output=True)
    subprocess.run([str(binary)], check=True, capture_output=True)

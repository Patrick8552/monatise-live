"""Execute the EA's actual pending lifecycle functions against a fake broker."""
from pathlib import Path
import re
import shutil
import subprocess

import pytest


def test_native_pending_entry_lease_expiry_restart_revocation_and_fill_races(tmp_path):
    compiler = shutil.which('c++')
    if compiler is None:
        pytest.skip('C++ compiler unavailable')
    implementation = Path('mt5/Experts/MonatisePendingEntry.mqh').read_text()
    implementation = re.sub(r'string (rows|pair)\[\];', r'std::vector<string> \1;', implementation)
    source = tmp_path / 'pending.cpp'
    source.write_text(r'''
#include <string>
#include <map>
#include <vector>
#include <algorithm>
using string=std::string; using ulong=unsigned long; using datetime=long;
enum {ACCOUNT_LOGIN,ORDER_TYPE,ORDER_MAGIC,ORDER_COMMENT,ORDER_TIME_EXPIRATION,ORDER_PRICE_OPEN,ORDER_SL,ORDER_TP};
const int TRADE_RETCODE_DONE=10009, TRADE_RETCODE_NO_CHANGES=10025;
const int ORDER_TYPE_BUY_LIMIT=2, ORDER_TYPE_SELL_LIMIT=3, ORDER_TYPE_BUY_STOP=4, ORDER_TYPE_SELL_STOP=5, ORDER_TIME_SPECIFIED=2;
const string ACCOUNT_SERVER="server";
string InpExpectedAccount="123", InpExpectedServer="broker", InpExpectedCurrency="USD", InpBridgeSecret="secret";
long InpMagicNumber=9, clock_now=1000;
bool InpExecutionEnabled=true, InpMasterAccountApproved=true, identity=true, permission=true, delete_ok=true, modify_ok=true;
struct Order {ulong ticket; string comment; long magic=9,type=2,expiry=1100; double entry=100,sl=90,tp=125;};
std::vector<Order> orders;
int selected=0, deleted=0, modified=0;
std::map<string,double> globals;
std::map<string,string> fields;
long AccountInfoInteger(int) {return 123;} string AccountInfoString(string) {return "broker";}
string IntegerToString(long n) {return std::to_string(n);}
string StringSubstr(string s,int p,int n=-1) {return s.substr(p,n<0?string::npos:n);}
int StringFind(string s,string q) {auto p=s.find(q);return p==string::npos?-1:p;}
string Sha256Hex(string) {return "server_hash";}
datetime TimeGMT() {return clock_now;}
bool GlobalVariableCheck(string key) {return globals.count(key);}
double GlobalVariableGet(string key) {return globals[key];}
long GlobalVariableSet(string key,double value) {globals[key]=value;return clock_now;}
void GlobalVariablesFlush() {}
bool IdentityMatches() {return identity;} bool TradingPermission() {return permission;}
int OrdersTotal() {return orders.size();}
ulong OrderGetTicket(int i) {selected=i;return orders[i].ticket;}
bool OrderSelect(ulong ticket) {for(int i=0;i<(int)orders.size();i++) if(orders[i].ticket==ticket) {selected=i;return true;} return false;}
long OrderGetInteger(int k) {auto o=orders[selected];return k==ORDER_MAGIC?o.magic:k==ORDER_TYPE?o.type:o.expiry;}
string OrderGetString(int) {return orders[selected].comment;}
double OrderGetDouble(int k) {auto o=orders[selected];return k==ORDER_PRICE_OPEN?o.entry:k==ORDER_SL?o.sl:o.tp;}
datetime BrokerTimeToUtc(datetime d) {return d;} long BrokerUtcOffsetSeconds() {return 0;}
template<typename... Args> void PrintFormat(string,Args...) {}
struct Broker {
 void SetAsyncMode(bool) {}
 bool OrderDelete(ulong t) {deleted++;if(!delete_ok) return false;orders.erase(std::remove_if(orders.begin(),orders.end(),[t](Order o){return o.ticket==t;}),orders.end());return true;}
 int ResultRetcode() {return delete_ok?10009:10029;}
 bool OrderModify(ulong ticket,double entry,double sl,double tp,int mode,datetime until,int) {
   modified++; if(!modify_ok || !OrderSelect(ticket)) return false;
   auto &o=orders[selected];
   if(entry!=o.entry || sl!=o.sl || tp!=o.tp || mode!=ORDER_TIME_SPECIFIED) return false;
   o.expiry=until;return true;
 }
} Trade;
string JsonString(string,string key) {return fields[key];}
bool DecodeBase64(string,string &out) {out="manifest";return true;}
string HmacSha256(string,string) {return "authentic";}
int StringCompare(string a,string b,bool) {return a.compare(b);}
long StringToInteger(string s) {try{return std::stol(s);}catch(...){return 0;}}
int StringSplit(string s,char c,std::vector<string>&v) {v.clear();size_t a=0,b;while((b=s.find(c,a))!=string::npos){v.push_back(s.substr(a,b-a));a=b+1;}if(a<s.size())v.push_back(s.substr(a));return v.size();}
''' + implementation + r'''
void reset() {
 clock_now=1000; identity=permission=delete_ok=modify_ok=InpExecutionEnabled=InpMasterAccountApproved=true;
 orders={{7,"MNP:abcdef"},{8,"MNT:legacy"},{9,"MNP:foreign",77}}; globals.clear(); deleted=modified=0;
 PreparePendingEntry("MNP:abcdef",1100,1015);
 fields={{"pending_manifest_signature","authentic"},{"nonce","nonce"},{"account","123"},{"server","broker"},{"currency","USD"},{"valid_until","1020"},{"leases","7|1020|1100"}};
}
int main() {
 reset(); if(PreparePendingEntry("MNP:abcdef",1200,1015)) return 1; // uncertain submission cannot duplicate
 ApplyPendingManifest("","nonce");
 if(orders[0].expiry!=1100 || modified!=0 || deleted!=0 || orders[0].sl!=90 || orders[0].tp!=125
    || globals[PendingKey("MNP:abcdef","lease")]!=1020) return 2;
 reset(); fields["leases"]=""; ApplyPendingManifest("","nonce");
 if(orders.size()!=2 || deleted!=1 || orders[0].ticket!=8 || orders[1].ticket!=9) return 3;
 reset(); delete_ok=false; fields["leases"]=""; ApplyPendingManifest("","nonce");
 if(deleted!=1 || !GlobalVariableCheck(PendingKey("MNP:abcdef","revoked"))) return 4;
 fields["leases"]="7|1020|1100"; ApplyPendingManifest("","nonce"); if(deleted!=2 || modified) return 5;
 delete_ok=true; GuardPendingEntries(false); if(orders.size()!=2 || deleted!=3) return 6;
 reset(); GuardPendingEntries(true); if(orders.size()!=2 || deleted!=1) return 7; // restart cancels only owned pending
 reset(); clock_now=1016; GuardPendingEntries(false); if(deleted!=1) return 8; // local lease expires before broker deadline
 reset(); InpExecutionEnabled=false; GuardPendingEntries(false); if(deleted!=1) return 9;
 reset(); orders[0].expiry=1008; fields["pending_manifest_signature"]="tampered"; ApplyPendingManifest("","nonce"); if(modified || deleted) return 10;
 reset(); orders[0].expiry=1008; ApplyPendingManifest("","replayed-nonce"); if(modified || deleted) return 11;
 reset(); fields["leases"]="7|1200|1200"; ApplyPendingManifest("","nonce"); if(deleted!=1 || modified) return 12;
 reset(); globals[PendingKey("MNP:abcdef","expiry")]=1005; ApplyPendingManifest("","nonce"); if(deleted!=1) return 13;
 reset(); orders.erase(orders.begin()); ApplyPendingManifest("","nonce"); if(deleted || modified) return 14; // already filled: no close
 reset(); fields["leases"]="7|1008|1008"; modify_ok=false; ApplyPendingManifest("","nonce"); if(modified!=1 || deleted!=1) return 15;
 reset(); permission=false; fields["leases"]=""; ApplyPendingManifest("","nonce"); if(deleted) return 16;
 permission=true; GuardPendingEntries(false); if(deleted!=1) return 17;
 reset(); fields["leases"]="7|1008|1008"; ApplyPendingManifest("","nonce"); if(orders[0].expiry!=1008 || modified!=1) return 18;
 reset(); fields["leases"]="7|1020|1200"; ApplyPendingManifest("","nonce"); if(deleted!=1 || modified) return 19; // never extend approval
 reset(); globals.erase(PendingKey("MNP:abcdef","lease")); GuardPendingEntries(false); if(deleted!=1) return 20;
 reset(); if(PreparePendingEntry("MNP:new",2801,1015) || PreparePendingEntry("MNP:new",2800,1021)) return 21;
 if(!PreparePendingEntry("MNP:new",2800,1020)) return 22;
 reset(); orders[0].expiry=1200; GuardPendingEntries(false); if(deleted!=1) return 23; // broker deadline tampering
 reset(); fields["leases"]="7|1020"; ApplyPendingManifest("","nonce"); if(deleted!=1) return 24; // old protocol fails closed
 reset(); ApplyPendingManifest("","nonce"); clock_now=1021; GuardPendingEntries(false); if(deleted!=1) return 25;
 return 0;
}
''')
    binary = tmp_path / 'pending'
    subprocess.run([compiler, '-std=c++17', str(source), '-o', str(binary)], check=True, capture_output=True)
    subprocess.run([str(binary)], check=True, capture_output=True)

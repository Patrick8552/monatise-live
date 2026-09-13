#property copyright "Monatise"
#property version   "1.18"
#property strict
#property description "Account-bound FTMO bridge. Telegram never talks directly to the broker."

#include <Trade/Trade.mqh>
#include "MonatiseBrokerResults.mqh"
#include "MonatiseMultiTP.mqh"

input bool InpMultiTPEnabled = false; // Must match server rollout; no autonomous trading.

input string InpControlPlaneUrl        = "https://monatise-live.onrender.com";
input string InpBridgeSecret           = "";       // Set in MT5; never commit the value.
input string InpExpectedAccount        = "";
input string InpExpectedServer         = "FTMO-Server";
input string InpExpectedCurrency       = "USD";
input string InpSymbols                = "XAUUSD,US100.cash,US500.cash,AAPL,EURUSD,GBPUSD,USDJPY,USDCHF,AUDUSD,NZDUSD,USDCAD"; // Non-crypto Telegram preview universe.
input bool   InpExecutionEnabled       = false;    // Independent local gate.
input bool   InpMasterAccountApproved  = false;    // Independent local gate.
input double InpRiskFraction           = 0.03;     // Absolute per-trade ceiling; may be configured lower.
input double InpDailyLossLimit         = 500.0;
input double InpTotalLossLimit         = 1000.0;
input double InpInitialAccountBalance  = 10000.0;
input int    InpMaximumOpenExposures   = 1;        // Positions plus pending orders.
input int    InpHeartbeatSeconds       = 2;
input int    InpHttpTimeoutMs          = 10000;
input int    InpMaximumSpreadTicks     = 80;
input int    InpMaximumDeviationPoints = 20;
input double InpGoldMaximumAdversePriceDeviation = 10.0; // Price units (USD/oz), signed Gold proposals only.
input long   InpMagicNumber            = 26082501;

string EA_VERSION = "1.18";
string JOURNAL_FILE = "monatise-ftmo-command-journal.csv";
string DynamicSymbols = "";
CTrade Trade;

string IsoTime(datetime value)
{
   MqlDateTime parts;
   TimeToStruct(value, parts);
   return StringFormat("%04d-%02d-%02dT%02d:%02d:%02d+00:00", parts.year, parts.mon, parts.day, parts.hour, parts.min, parts.sec);
}

string BrokerTime(datetime value)
{
   MqlDateTime parts;
   TimeToStruct(value, parts);
   return StringFormat("%04d-%02d-%02dT%02d:%02d:%02d", parts.year, parts.mon, parts.day, parts.hour, parts.min, parts.sec);
}

long BrokerUtcOffsetSeconds()
{
   return (long)TimeTradeServer() - (long)TimeGMT();
}

datetime BrokerTimeToUtc(datetime value)
{
   return (datetime)((long)value - BrokerUtcOffsetSeconds());
}

string JsonEscape(string value)
{
   StringReplace(value, "\\", "\\\\");
   StringReplace(value, "\"", "\\\"");
   StringReplace(value, "\r", "\\r");
   StringReplace(value, "\n", "\\n");
   return value;
}

string BytesToHex(const uchar &data[])
{
   string result = "";
   for(int index = 0; index < ArraySize(data); index++)
      result += StringFormat("%02x", data[index]);
   return result;
}

bool Sha256Bytes(const uchar &data[], uchar &digest[])
{
   uchar key[];
   ArrayResize(key, 0);
   ResetLastError();
   return CryptEncode(CRYPT_HASH_SHA256, data, key, digest) > 0;
}

string Sha256Hex(string value)
{
   // MT5 CryptEncode can fail on a zero-length input array. GET command
   // polling signs an empty body, so use the standard SHA-256 digest of an
   // empty byte string instead of producing an invalid canonical signature.
   if(value == "")
      return "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";
   uchar data[], digest[];
   StringToCharArray(value, data, 0, WHOLE_ARRAY, CP_UTF8);
   if(ArraySize(data) > 0 && data[ArraySize(data) - 1] == 0)
      ArrayResize(data, ArraySize(data) - 1);
   if(!Sha256Bytes(data, digest))
      return "";
   return BytesToHex(digest);
}

string HmacSha256(string secret, string message)
{
   uchar key[], inner[], outer[], data[], digest[], result[];
   StringToCharArray(secret, key, 0, WHOLE_ARRAY, CP_UTF8);
   if(ArraySize(key) > 0 && key[ArraySize(key) - 1] == 0)
      ArrayResize(key, ArraySize(key) - 1);
   if(ArraySize(key) > 64)
   {
      if(!Sha256Bytes(key, digest)) return "";
      ArrayCopy(key, digest);
      ArrayResize(key, ArraySize(digest));
   }
   int key_size = ArraySize(key);
   ArrayResize(key, 64);
   for(int index = key_size; index < 64; index++) key[index] = 0;
   ArrayResize(inner, 64);
   ArrayResize(outer, 64);
   for(int index = 0; index < 64; index++)
   {
      inner[index] = (uchar)(key[index] ^ 0x36);
      outer[index] = (uchar)(key[index] ^ 0x5c);
   }
   StringToCharArray(message, data, 0, WHOLE_ARRAY, CP_UTF8);
   if(ArraySize(data) > 0 && data[ArraySize(data) - 1] == 0)
      ArrayResize(data, ArraySize(data) - 1);
   ArrayCopy(inner, data, 64, 0, WHOLE_ARRAY);
   if(!Sha256Bytes(inner, digest)) return "";
   ArrayCopy(outer, digest, 64, 0, WHOLE_ARRAY);
   if(!Sha256Bytes(outer, result)) return "";
   return BytesToHex(result);
}

string RequestNonce()
{
   return StringFormat("%I64x%08x%08x", (long)TimeGMT(), (uint)GetTickCount(), (uint)MathRand());
}

bool SignedRequest(string method, string path, string body, string &response, int &status)
{
   if(StringLen(InpBridgeSecret) < 32)
   {
      Print("Monatise bridge blocked: bridge secret is absent or too short");
      return false;
   }
   string timestamp = IntegerToString((long)TimeGMT());
   string nonce = RequestNonce();
   string canonical = method + "\n" + path + "\n" + timestamp + "\n" + nonce + "\n" + Sha256Hex(body);
   string signature = HmacSha256(InpBridgeSecret, canonical);
   if(signature == "") return false;
   string headers = "Content-Type: application/json\r\n"
                  + "X-Monatise-Timestamp: " + timestamp + "\r\n"
                  + "X-Monatise-Nonce: " + nonce + "\r\n"
                  + "X-Monatise-Signature: " + signature + "\r\n";
   char request[], received[];
   StringToCharArray(body, request, 0, WHOLE_ARRAY, CP_UTF8);
   if(ArraySize(request) > 0 && request[ArraySize(request) - 1] == 0)
      ArrayResize(request, ArraySize(request) - 1);
   string response_headers;
   ResetLastError();
   status = WebRequest(method, InpControlPlaneUrl + path, headers, InpHttpTimeoutMs, request, received, response_headers);
   if(status == -1)
   {
      PrintFormat("Monatise WebRequest failed error=%d. Add the HTTPS URL to MT5 allowed URLs.", GetLastError());
      return false;
   }
   response = CharArrayToString(received, 0, WHOLE_ARRAY, CP_UTF8);
   return true;
}

bool IdentityMatches()
{
   string login = IntegerToString((long)AccountInfoInteger(ACCOUNT_LOGIN));
   string server = AccountInfoString(ACCOUNT_SERVER);
   string currency = AccountInfoString(ACCOUNT_CURRENCY);
   return InpExpectedAccount != "" && login == InpExpectedAccount
       && StringCompare(server, InpExpectedServer, false) == 0
       && StringCompare(currency, InpExpectedCurrency, false) == 0;
}

bool TradingPermission()
{
   return TerminalInfoInteger(TERMINAL_CONNECTED)
       && TerminalInfoInteger(TERMINAL_TRADE_ALLOWED)
       && MQLInfoInteger(MQL_TRADE_ALLOWED)
       && AccountInfoInteger(ACCOUNT_TRADE_ALLOWED)
       && AccountInfoInteger(ACCOUNT_TRADE_EXPERT);
}

string SymbolKey(string value)
{
   StringToUpper(value);
   string result = "";
   for(int index = 0; index < StringLen(value); index++)
   {
      ushort character = StringGetCharacter(value, index);
      if((character >= 65 && character <= 90) || (character >= 48 && character <= 57))
         result += ShortToString(character);
   }
   return result;
}

bool ResolveBrokerSymbol(string requested, string &resolved, string &reason)
{
   bool custom = false;
   bool exists = SymbolExist(requested, custom);
   string requested_key = SymbolKey(requested);
   int match_count = 0;
   int total = SymbolsTotal(false);
   for(int index = 0; index < total; index++)
   {
      string candidate = SymbolName(index, false);
      if(StringCompare(candidate, requested, false) == 0 || SymbolKey(candidate) == requested_key)
      {
         resolved = candidate;
         match_count++;
      }
   }
   if(match_count == 1)
      return true;
   if(match_count == 0 && exists)
   {
      resolved = requested;
      return true;
   }
   reason = match_count == 0 ? "symbol is not exposed by the connected FTMO terminal"
                             : "symbol normalization matched more than one broker instrument";
   resolved = "";
   return false;
}

string QuoteJson(string requested_symbol, string &resolved_symbol, string &reason)
{
   if(!ResolveBrokerSymbol(requested_symbol, resolved_symbol, reason))
      return "";
   MqlTick tick;
   if(!SymbolSelect(resolved_symbol, true))
   {
      reason = "broker symbol could not be selected in Market Watch";
      return "";
   }
   if(!SymbolIsSynchronized(resolved_symbol))
   {
      reason = "broker symbol data is not synchronized with the trade server";
      return "";
   }
   if(!SymbolInfoTick(resolved_symbol, tick))
   {
      reason = "SymbolInfoTick returned no quote";
      return "";
   }
   if(tick.bid <= 0 || tick.ask <= 0)
   {
      reason = "broker quote has a non-positive Bid or Ask";
      return "";
   }
   if(tick.ask <= tick.bid)
   {
      reason = "broker quote has a zero or inverted spread";
      return "";
   }
   datetime observed_utc = TimeGMT();
   datetime broker_time = (datetime)(tick.time_msc / 1000);
   long broker_offset_seconds = BrokerUtcOffsetSeconds();
   datetime broker_time_utc = (datetime)((long)broker_time - broker_offset_seconds);
   long quote_age_seconds = (long)observed_utc - (long)broker_time_utc;
   if(quote_age_seconds < -1)
   {
      reason = "broker tick timestamp is materially in the future";
      return "";
   }
   if(quote_age_seconds > 5)
   {
      reason = "broker tick is older than the 5-second execution limit";
      return "";
   }
   int digits = (int)SymbolInfoInteger(resolved_symbol, SYMBOL_DIGITS);
   double tick_size = SymbolInfoDouble(resolved_symbol, SYMBOL_TRADE_TICK_SIZE);
   double tick_value = SymbolInfoDouble(resolved_symbol, SYMBOL_TRADE_TICK_VALUE_LOSS);
   if(tick_value <= 0) tick_value = SymbolInfoDouble(resolved_symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_value_profit = SymbolInfoDouble(resolved_symbol, SYMBOL_TRADE_TICK_VALUE_PROFIT);
   double point = SymbolInfoDouble(resolved_symbol, SYMBOL_POINT);
   if(tick_size <= 0 || tick_value <= 0 || point <= 0)
   {
      reason = "broker symbol specification is incomplete";
      return "";
   }
   reason = "";
   return "\"" + JsonEscape(resolved_symbol) + "\":{"
      + "\"bid\":\"" + DoubleToString(tick.bid, digits) + "\","
      + "\"ask\":\"" + DoubleToString(tick.ask, digits) + "\","
      + "\"timestamp\":\"" + IsoTime(broker_time_utc) + "\","
      + "\"observed_at_utc\":\"" + IsoTime(observed_utc) + "\","
      + "\"quote_observed_at_utc\":\"" + IsoTime(broker_time_utc) + "\","
      + "\"broker_time\":\"" + BrokerTime(broker_time) + "\","
      + "\"broker_time_offset\":" + IntegerToString((int)broker_offset_seconds) + ","
      + "\"broker_time_offset_seconds\":" + IntegerToString((int)broker_offset_seconds) + ","
      + "\"terminal_local_time\":\"" + BrokerTime(TimeLocal()) + "\","
      + "\"digits\":" + IntegerToString(digits) + ","
      + "\"point\":\"" + DoubleToString(point, digits) + "\","
      + "\"tick_size\":\"" + DoubleToString(tick_size, digits) + "\","
      + "\"tick_value\":\"" + DoubleToString(tick_value, 8) + "\","
      + "\"tick_value_loss\":\"" + DoubleToString(tick_value, 8) + "\","
      + "\"tick_value_profit\":\"" + DoubleToString(tick_value_profit, 8) + "\","
      + "\"contract_size\":\"" + DoubleToString(SymbolInfoDouble(resolved_symbol, SYMBOL_TRADE_CONTRACT_SIZE), 8) + "\","
      + "\"volume_min\":\"" + DoubleToString(SymbolInfoDouble(resolved_symbol, SYMBOL_VOLUME_MIN), 8) + "\","
      + "\"volume_max\":\"" + DoubleToString(SymbolInfoDouble(resolved_symbol, SYMBOL_VOLUME_MAX), 8) + "\","
      + "\"volume_step\":\"" + DoubleToString(SymbolInfoDouble(resolved_symbol, SYMBOL_VOLUME_STEP), 8) + "\","
      + "\"stops_level\":\"" + IntegerToString((int)SymbolInfoInteger(resolved_symbol, SYMBOL_TRADE_STOPS_LEVEL)) + "\","
      + "\"freeze_level\":\"" + IntegerToString((int)SymbolInfoInteger(resolved_symbol, SYMBOL_TRADE_FREEZE_LEVEL)) + "\","
      + "\"expiration_mode\":\"" + IntegerToString((int)SymbolInfoInteger(resolved_symbol, SYMBOL_EXPIRATION_MODE)) + "\","
      + "\"filling_mode\":\"" + IntegerToString((int)SymbolInfoInteger(resolved_symbol, SYMBOL_FILLING_MODE)) + "\","
      + "\"order_mode\":\"" + IntegerToString((int)SymbolInfoInteger(resolved_symbol, SYMBOL_ORDER_MODE)) + "\","
      + "\"trade_mode\":\"" + IntegerToString((int)SymbolInfoInteger(resolved_symbol, SYMBOL_TRADE_MODE)) + "\"}";
}

string PositionsJson()
{
   string result = "[";
   for(int index = 0; index < PositionsTotal(); index++)
   {
      ulong ticket = PositionGetTicket(index);
      if(ticket == 0) continue;
      if(result != "[") result += ",";
      result += "{\"ticket\":\"" + IntegerToString((long)ticket) + "\",\"symbol\":\"" + JsonEscape(PositionGetString(POSITION_SYMBOL))
             + "\",\"identifier\":\"" + IntegerToString(PositionGetInteger(POSITION_IDENTIFIER))
             + "\",\"magic\":\"" + IntegerToString(PositionGetInteger(POSITION_MAGIC))
             + "\",\"type\":" + IntegerToString((int)PositionGetInteger(POSITION_TYPE))
             + ",\"volume\":\"" + DoubleToString(PositionGetDouble(POSITION_VOLUME), 8)
             + "\",\"price_open\":\"" + DoubleToString(PositionGetDouble(POSITION_PRICE_OPEN), 8)
             + "\",\"price_current\":\"" + DoubleToString(PositionGetDouble(POSITION_PRICE_CURRENT), 8)
             + "\",\"profit\":\"" + DoubleToString(PositionGetDouble(POSITION_PROFIT), 2)
             + "\",\"comment\":\"" + JsonEscape(PositionGetString(POSITION_COMMENT))
             + "\",\"sl\":\"" + DoubleToString(PositionGetDouble(POSITION_SL), 8)
             + "\",\"tp\":\"" + DoubleToString(PositionGetDouble(POSITION_TP), 8) + "\"}";
   }
   return result + "]";
}


string ManagementDealJson(ulong deal)
{
   long entry = HistoryDealGetInteger(deal, DEAL_ENTRY);
   if(entry != DEAL_ENTRY_IN && entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_OUT_BY) return "";
   long reason = HistoryDealGetInteger(deal, DEAL_REASON);
   string label = reason == DEAL_REASON_TP ? "TP" : reason == DEAL_REASON_SL ? "SL" :
                  reason == DEAL_REASON_CLIENT ? "CLIENT" : reason == DEAL_REASON_MOBILE ? "MOBILE" :
                  reason == DEAL_REASON_WEB ? "WEB" : reason == DEAL_REASON_EXPERT ? "EXPERT" : "UNKNOWN";
   return "{\"deal_id\":\"" + IntegerToString((long)deal)
      + "\",\"position_id\":\"" + IntegerToString(HistoryDealGetInteger(deal, DEAL_POSITION_ID))
      + "\",\"order_id\":\"" + IntegerToString(HistoryDealGetInteger(deal, DEAL_ORDER))
      + "\",\"entry\":\"" + (entry == DEAL_ENTRY_IN ? "in" : "out") + "\",\"reason\":\"" + label
      + "\",\"time\":\"" + IsoTime(BrokerTimeToUtc((datetime)HistoryDealGetInteger(deal, DEAL_TIME)))
      + "\",\"volume\":\"" + DoubleToString(HistoryDealGetDouble(deal, DEAL_VOLUME), 8)
      + "\",\"profit\":\"" + DoubleToString(HistoryDealGetDouble(deal, DEAL_PROFIT), 8)
      + "\",\"commission\":\"" + DoubleToString(HistoryDealGetDouble(deal, DEAL_COMMISSION), 8)
      + "\",\"swap\":\"" + DoubleToString(HistoryDealGetDouble(deal, DEAL_SWAP), 8)
      + "\",\"fee\":\"" + DoubleToString(HistoryDealGetDouble(deal, DEAL_FEE), 8)
      + "\",\"price\":\"" + DoubleToString(HistoryDealGetDouble(deal, DEAL_PRICE), 8)
      + "\",\"comment\":\"" + JsonEscape(HistoryDealGetString(deal, DEAL_COMMENT)) + "\"}";
}

string ManagementDealsJson()
{
   // Query full history for each open owned position, plus recent closed ones.
   // Bounded transport: missing history is detected by the server and stops management.
   string result = "[";
   int count = 0;
   for(int p=0; p<PositionsTotal() && count<768; p++)
   {
      ulong ticket = PositionGetTicket(p);
      if(ticket == 0 || PositionGetInteger(POSITION_MAGIC) != InpMagicNumber) continue;
      ulong identifier = (ulong)PositionGetInteger(POSITION_IDENTIFIER);
      if(!HistorySelectByPosition(identifier)) continue;
      int total = HistoryDealsTotal();
      for(int i=0; i<total && count<768; i++)
      {
         string row = ManagementDealJson(HistoryDealGetTicket(i));
         if(row == "") continue;
         if(result != "[") result += ",";
         result += row; count++;
      }
   }
   if(HistorySelect(TimeTradeServer()-30*86400, TimeTradeServer()))
   {
      for(int i=HistoryDealsTotal()-1; i>=0 && count<1024; i--)
      {
         ulong deal = HistoryDealGetTicket(i);
         // Include manual exits too: their magic can be zero. The server binds
         // position identifiers to previously approved owned opening trades.
         string row = ManagementDealJson(deal);
         if(row == "") continue;
         if(result != "[") result += ",";
         result += row; count++;
      }
   }
   return result + "]";
}

bool ValidateProfitIntent(string payload, string &reason)
{
   string operation = JsonString(payload, "operation");
   if(operation == "open" && JsonString(payload, "multi_tp_version") == "") return true;
   bool managed = JsonString(payload, "managed_trade_id") != "";
   if(operation != "open" && !managed && operation != "partial_close" && operation != "modify_targets") return true;
   if(!InpMultiTPEnabled && operation != "close" && operation != "sl" && operation != "breakeven") { reason = "local multi-target gate is disabled"; return false; }
   if(operation == "open")
   {
      int count = (int)StringToInteger(JsonString(payload, "target_count"));
      if(JsonString(payload, "multi_tp_version") != "1" || count < 1 || count > 4)
         { reason = "unsupported target plan"; return false; }
      string symbol = JsonString(payload, "symbol");
      MqlTick quote;
      if(!SymbolInfoTick(symbol, quote)) { reason = "target quote unavailable"; return false; }
      bool buy = JsonString(payload, "side") == "buy";
      double entry = JsonString(payload, "order_type") == "market" ? (buy ? quote.ask : quote.bid) : StringToDouble(JsonString(payload, "entry"));
      double stop = StringToDouble(JsonString(payload, "stop_loss"));
      double tick = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
      double minimum = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN), step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
      double rr = StringToDouble(JsonString(payload, "minimum_target_rr"));
      double increment = StringToDouble(JsonString(payload, "minimum_target_increment_r"));
      if(rr <= 0 || increment <= 0 || minimum <= 0 || step <= 0) { reason = "invalid target policy"; return false; }
      double distance = MathMax((double)SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL), (double)SymbolInfoInteger(symbol, SYMBOL_TRADE_FREEZE_LEVEL))*SymbolInfoDouble(symbol, SYMBOL_POINT);
      double total = 0, previous = entry;
      for(int i=0; i<count; i++)
      {
         double price = StringToDouble(JsonString(payload, "tp_"+IntegerToString(i)+"_price"));
         double volume = StringToDouble(JsonString(payload, "tp_"+IntegerToString(i)+"_volume"));
         if(!MultiTPLevelValid(entry, stop, price, previous, buy, tick, distance, rr, increment, i==0)
            || !MathIsValidNumber(volume) || volume < minimum-1e-8 || MathAbs(volume/step-MathRound(volume/step))>1e-8)
            { reason = "invalid target geometry/allocation at final quote"; return false; }
         total += volume; previous = price;
      }
      if(MathAbs(total-StringToDouble(JsonString(payload, "volume")))>1e-8
         || MathAbs(previous-StringToDouble(JsonString(payload, "take_profit")))>1e-8)
         { reason = "ladder volume or final TP mismatch"; return false; }
      return true;
   }
   ulong ticket = (ulong)StringToInteger(JsonString(payload, "target_id"));
   if(!managed || !PositionSelectByTicket(ticket) || PositionGetInteger(POSITION_MAGIC) != InpMagicNumber
      || IntegerToString(PositionGetInteger(POSITION_IDENTIFIER)) != JsonString(payload, "position_identifier")
      || MathAbs(PositionGetDouble(POSITION_VOLUME)-StringToDouble(JsonString(payload, "expected_remaining_volume")))>1e-8)
      { reason = "managed position identity/volume changed"; return false; }
   string symbol = PositionGetString(POSITION_SYMBOL);
   if(JsonString(payload, "symbol") != symbol) { reason = "managed symbol mismatch"; return false; }
   MqlTick quote;
   if(!SymbolInfoTick(symbol, quote) || TimeGMT()-BrokerTimeToUtc(quote.time)>5)
      { reason = "management quote is stale"; return false; }
   bool buy = PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY;
   if(operation == "partial_close")
   {
      double tick_size = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
      if(tick_size <= 0 || quote.ask <= quote.bid || (quote.ask-quote.bid)/tick_size > InpMaximumSpreadTicks)
         { reason = "partial spread exceeds policy"; return false; }
      double final_target = PositionGetDouble(POSITION_TP);
      if(final_target > 0 && (buy ? quote.bid >= final_target : quote.ask <= final_target))
         { reason = "final broker target already reached; await deal reconciliation"; return false; }
      double volume = StringToDouble(JsonString(payload, "volume"));
      double trigger = StringToDouble(JsonString(payload, "trigger_price"));
      if(trigger <= 0 || !MathIsValidNumber(trigger) || (buy ? quote.bid<trigger : quote.ask>trigger)
         || !MultiTPVolumeValid(volume, PositionGetDouble(POSITION_VOLUME), SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN), SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP)))
         { reason = "partial target/volume is no longer executable"; return false; }
   }
   if(operation == "sl" || operation == "breakeven" || operation == "modify_targets")
   {
      double level = StringToDouble(JsonString(payload, "value"));
      if(operation == "breakeven") level = PositionGetDouble(POSITION_PRICE_OPEN);
      double distance = MathMax((double)SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL), (double)SymbolInfoInteger(symbol, SYMBOL_TRADE_FREEZE_LEVEL))*SymbolInfoDouble(symbol, SYMBOL_POINT);
      double old = PositionGetDouble(POSITION_SL);
      bool target = operation == "modify_targets";
      if(level <= 0 || !MathIsValidNumber(level)
         || (target && (buy ? level-quote.bid : quote.ask-level)<distance)
         || (!target && ((buy ? quote.bid-level : level-quote.ask)<distance || (old>0 && (buy ? level<old : level>old)))))
         { reason = "managed modification worsens stop or violates stop/freeze distance"; return false; }
   }
   return true;
}

void ExecutePartialProfit(string payload, string command_id)
{
   string reason;
   // Validate again at the broker boundary; an opposite netting deal must never reverse.
   if(!ValidateProfitIntent(payload, reason))
   {
      JournalAppend(command_id, "rejected", "", reason); Acknowledge(command_id, "rejected", "", reason); return;
   }
   ulong ticket = (ulong)StringToInteger(JsonString(payload, "target_id"));
   MqlTradeRequest request = {};
   MqlTradeResult result = {};
   MqlTradeCheckResult check = {};
   request.action = TRADE_ACTION_DEAL;
   request.position = ticket; // Required for hedging, also binds the netting reduction.
   request.symbol = PositionGetString(POSITION_SYMBOL);
   request.magic = InpMagicNumber;
   request.volume = StringToDouble(JsonString(payload, "volume"));
   request.type = PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
   MqlTick quote;
   if(!SymbolInfoTick(request.symbol, quote)) { Acknowledge(command_id, "broker_uncertain", "", "partial quote unavailable"); return; }
   request.price = request.type == ORDER_TYPE_SELL ? quote.bid : quote.ask;
   request.deviation = MathMax(0, InpMaximumDeviationPoints);
   request.comment = "MNT:" + StringSubstr(command_id, 0, 16);
   long filling = SymbolInfoInteger(request.symbol, SYMBOL_FILLING_MODE);
   if((filling & SYMBOL_FILLING_FOK) != 0) request.type_filling = ORDER_FILLING_FOK;
   else if((filling & SYMBOL_FILLING_IOC) != 0) request.type_filling = ORDER_FILLING_IOC;
   else { JournalAppend(command_id, "rejected", "", "unsupported partial filling mode"); Acknowledge(command_id, "rejected", "", "unsupported partial filling mode"); return; }
   if(!OrderCheck(request, check))
   {
      JournalAppend(command_id, "rejected", "", check.comment); AcknowledgeEvidence(command_id, "rejected", "", check.comment, false, IntegerToString((int)check.retcode), "", "", "", "", "", ""); return;
   }
   if(!ValidateProfitIntent(payload, reason))
   {
      JournalAppend(command_id, "rejected", "", reason); Acknowledge(command_id, "rejected", "", reason); return;
   }
   bool sent = OrderSend(request, result);
   string status = BrokerResultStatus((int)result.retcode, "partial_close", "market", (long)result.order, result.price, result.volume);
   if(!sent && status == "reconciled") status = "broker_uncertain";
   string order = IntegerToString((long)result.order);
   JournalAppend(command_id, status, order, result.comment);
   AcknowledgeEvidence(command_id, status, order, result.comment, true, IntegerToString((int)result.retcode), DoubleToString(request.price, 8), DoubleToString(result.price, 8), DoubleToString(result.price-request.price, 8), DoubleToString(result.volume, 8), "", "");
}


string OrdersJson()
{
   string result = "[";
   for(int index = 0; index < OrdersTotal(); index++)
   {
      ulong ticket = OrderGetTicket(index);
      if(ticket == 0) continue;
      if(result != "[") result += ",";
      result += "{\"ticket\":\"" + IntegerToString((long)ticket) + "\",\"symbol\":\"" + JsonEscape(OrderGetString(ORDER_SYMBOL))
             + "\",\"magic\":\"" + IntegerToString(OrderGetInteger(ORDER_MAGIC))
             + "\",\"type\":" + IntegerToString((int)OrderGetInteger(ORDER_TYPE))
             + ",\"volume\":\"" + DoubleToString(OrderGetDouble(ORDER_VOLUME_CURRENT), 8)
             + "\",\"price_open\":\"" + DoubleToString(OrderGetDouble(ORDER_PRICE_OPEN), 8)
             + "\",\"sl\":\"" + DoubleToString(OrderGetDouble(ORDER_SL), 8)
             + "\",\"tp\":\"" + DoubleToString(OrderGetDouble(ORDER_TP), 8)
             + "\",\"comment\":\"" + JsonEscape(OrderGetString(ORDER_COMMENT)) + "\"}";
   }
   return result + "]";
}

double DailyStartEquity()
{
   MqlDateTime parts;
   TimeToStruct(TimeGMT(), parts);
   string key = StringFormat("MNT.DAILY.%I64d.%04d%02d%02d", AccountInfoInteger(ACCOUNT_LOGIN), parts.year, parts.mon, parts.day);
   if(!GlobalVariableCheck(key))
      GlobalVariableSet(key, AccountInfoDouble(ACCOUNT_EQUITY));
   return GlobalVariableGet(key);
}

bool CurrentOpenRisk(double &risk, string &reason)
{
   risk = 0.0;
   for(int index = 0; index < PositionsTotal(); index++)
   {
      ulong ticket = PositionGetTicket(index);
      if(ticket == 0) continue;
      string symbol = PositionGetString(POSITION_SYMBOL);
      double stop = PositionGetDouble(POSITION_SL);
      if(stop <= 0) { reason = "an open position has no protective stop"; return false; }
      double tick_size = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
      double tick_value = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE_LOSS);
      if(tick_value <= 0) tick_value = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
      if(tick_size <= 0 || tick_value <= 0) { reason = "open-position symbol risk cannot be calculated"; return false; }
      risk += MathAbs(PositionGetDouble(POSITION_PRICE_OPEN) - stop) / tick_size
            * tick_value * PositionGetDouble(POSITION_VOLUME);
   }
   for(int index = 0; index < OrdersTotal(); index++)
   {
      ulong ticket = OrderGetTicket(index);
      if(ticket == 0) continue;
      string symbol = OrderGetString(ORDER_SYMBOL);
      double stop = OrderGetDouble(ORDER_SL);
      if(stop <= 0) { reason = "a pending order has no protective stop"; return false; }
      double tick_size = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
      double tick_value = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE_LOSS);
      if(tick_value <= 0) tick_value = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
      if(tick_size <= 0 || tick_value <= 0) { reason = "pending-order symbol risk cannot be calculated"; return false; }
      risk += MathAbs(OrderGetDouble(ORDER_PRICE_OPEN) - stop) / tick_size
            * tick_value * OrderGetDouble(ORDER_VOLUME_CURRENT);
   }
   return true;
}

bool CsvContainsSymbol(string csv, string symbol)
{
   string values[];
   int count = StringSplit(csv, ',', values);
   string requested_key = SymbolKey(symbol);
   for(int index = 0; index < count; index++)
   {
      StringTrimLeft(values[index]); StringTrimRight(values[index]);
      if(SymbolKey(values[index]) == requested_key)
         return true;
   }
   return false;
}

string HeartbeatSymbols()
{
   string result = InpSymbols;
   string requested[];
   int count = StringSplit(DynamicSymbols, ',', requested);
   for(int index = 0; index < count; index++)
   {
      StringTrimLeft(requested[index]); StringTrimRight(requested[index]);
      if(requested[index] != "" && !CsvContainsSymbol(result, requested[index]))
         result += "," + requested[index];
   }
   // Keep every exposed symbol priced even after its temporary quote demand ends.
   for(int index = 0; index < PositionsTotal(); index++)
   {
      if(PositionGetTicket(index) == 0) continue;
      string symbol = PositionGetString(POSITION_SYMBOL);
      if(symbol != "" && !CsvContainsSymbol(result, symbol)) result += "," + symbol;
   }
   for(int index = 0; index < OrdersTotal(); index++)
   {
      if(OrderGetTicket(index) == 0) continue;
      string symbol = OrderGetString(ORDER_SYMBOL);
      if(symbol != "" && !CsvContainsSymbol(result, symbol)) result += "," + symbol;
   }
   return result;
}

string BuildHeartbeat()
{
   datetime observed_utc = TimeGMT();
   string quotes = "{";
   string diagnostics = "{";
   string symbols[];
   int count = StringSplit(HeartbeatSymbols(), ',', symbols);
   for(int index = 0; index < count; index++)
   {
      StringTrimLeft(symbols[index]); StringTrimRight(symbols[index]);
      string resolved = "";
      string reason = "";
      string quote = QuoteJson(symbols[index], resolved, reason);
      if(quote != "")
      {
         if(quotes != "{") quotes += ",";
         quotes += quote;
      }
      if(diagnostics != "{") diagnostics += ",";
      diagnostics += "\"" + JsonEscape(symbols[index]) + "\":{"
                  + "\"requested_symbol\":\"" + JsonEscape(symbols[index]) + "\","
                  + "\"resolved_symbol\":\"" + JsonEscape(resolved) + "\","
                  + "\"status\":\"" + (quote == "" ? "unavailable" : "quoted") + "\","
                  + "\"reason\":\"" + JsonEscape(reason) + "\"}";
   }
   quotes += "}";
   diagnostics += "}";
   return "{"
      + "\"account_id\":\"" + IntegerToString((long)AccountInfoInteger(ACCOUNT_LOGIN)) + "\","
      + "\"server\":\"" + JsonEscape(AccountInfoString(ACCOUNT_SERVER)) + "\","
      + "\"currency\":\"" + JsonEscape(AccountInfoString(ACCOUNT_CURRENCY)) + "\","
      + "\"balance\":\"" + DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2) + "\","
      + "\"equity\":\"" + DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY), 2) + "\","
      + "\"free_margin\":\"" + DoubleToString(AccountInfoDouble(ACCOUNT_MARGIN_FREE), 2) + "\","
      + "\"daily_start_equity\":\"" + DoubleToString(DailyStartEquity(), 2) + "\","
      + "\"initial_balance\":\"" + DoubleToString(InpInitialAccountBalance, 2) + "\","
      + "\"daily_loss_limit\":\"" + DoubleToString(InpDailyLossLimit, 2) + "\","
      + "\"total_loss_limit\":\"" + DoubleToString(InpTotalLossLimit, 2) + "\","
      + "\"terminal_connected\":" + (TerminalInfoInteger(TERMINAL_CONNECTED) ? "true" : "false") + ","
      + "\"trade_allowed\":" + (TradingPermission() ? "true" : "false") + ","
      + "\"ea_attached\":true,"
      + "\"terminal_build\":\"" + IntegerToString((int)TerminalInfoInteger(TERMINAL_BUILD)) + "\","
      + "\"ea_version\":\"" + EA_VERSION + "\","
      + "\"multi_tp_version\":" + (InpMultiTPEnabled ? "1" : "0") + ","
      + "\"account_margin_mode\":" + IntegerToString(AccountInfoInteger(ACCOUNT_MARGIN_MODE)) + ","
      + "\"deals\":" + (InpMultiTPEnabled ? ManagementDealsJson() : "[]") + ","
      + "\"gold_price_guard_version\":1,"
      + "\"gold_maximum_adverse_price_deviation\":\"" + DoubleToString(MathMax(0, InpGoldMaximumAdversePriceDeviation), 8) + "\","
      + "\"observed_at_utc\":\"" + IsoTime(observed_utc) + "\","
      + "\"broker_time\":\"" + BrokerTime(TimeTradeServer()) + "\","
      + "\"broker_time_offset\":" + IntegerToString((int)BrokerUtcOffsetSeconds()) + ","
      + "\"terminal_local_time\":\"" + BrokerTime(TimeLocal()) + "\","
      + "\"positions\":" + PositionsJson() + ","
      + "\"orders\":" + OrdersJson() + ","
      + "\"quotes\":" + quotes + ","
      + "\"quote_diagnostics\":" + diagnostics + "}";
}

string JsonString(string json, string key)
{
   string marker = "\"" + key + "\":\"";
   int start = StringFind(json, marker);
   if(start < 0) return "";
   start += StringLen(marker);
   string value = "";
   bool escaped = false;
   for(int index = start; index < StringLen(json); index++)
   {
      ushort character = StringGetCharacter(json, index);
      if(escaped) { value += ShortToString(character); escaped = false; continue; }
      if(character == '\\') { escaped = true; continue; }
      if(character == '"') break;
      value += ShortToString(character);
   }
   return value;
}

string JsonTopLevelObject(string json, string key)
{
   int container_depth = 0;
   int length = StringLen(json);
   for(int index = 0; index < length; index++)
   {
      ushort character = StringGetCharacter(json, index);
      if(character == 34)
      {
         int key_end = index + 1;
         bool key_escaped = false;
         for(; key_end < length; key_end++)
         {
            ushort key_character = StringGetCharacter(json, key_end);
            if(key_escaped) { key_escaped = false; continue; }
            if(key_character == 92) { key_escaped = true; continue; }
            if(key_character == 34) break;
         }
         if(key_end >= length) return "";
         string candidate = StringSubstr(json, index + 1, key_end - index - 1);
         if(container_depth == 1 && candidate == key)
         {
            int value_start = key_end + 1;
            while(value_start < length && StringGetCharacter(json, value_start) == 32) value_start++;
            if(value_start >= length || StringGetCharacter(json, value_start) != 58) return "";
            value_start++;
            while(value_start < length && StringGetCharacter(json, value_start) == 32) value_start++;
            if(value_start >= length || StringGetCharacter(json, value_start) != 123) return "";
            int object_depth = 0;
            bool object_string = false;
            bool object_escaped = false;
            for(int cursor = value_start; cursor < length; cursor++)
            {
               ushort value_character = StringGetCharacter(json, cursor);
               if(object_string)
               {
                  if(object_escaped) { object_escaped = false; continue; }
                  if(value_character == 92) { object_escaped = true; continue; }
                  if(value_character == 34) object_string = false;
                  continue;
               }
               if(value_character == 34) { object_string = true; continue; }
               if(value_character == 123) object_depth++;
               else if(value_character == 125)
               {
                  object_depth--;
                  if(object_depth == 0)
                     return StringSubstr(json, value_start, cursor - value_start + 1);
               }
            }
            return "";
         }
         index = key_end;
         continue;
      }
      if(character == 123 || character == 91) container_depth++;
      else if(character == 125 || character == 93) container_depth--;
   }
   return "";
}

bool DecodeBase64(string encoded, string &decoded)
{
   uchar source[], key[], result[];
   StringToCharArray(encoded, source, 0, WHOLE_ARRAY, CP_UTF8);
   if(ArraySize(source) > 0 && source[ArraySize(source) - 1] == 0) ArrayResize(source, ArraySize(source) - 1);
   ArrayResize(key, 0);
   if(CryptDecode(CRYPT_BASE64, source, key, result) <= 0) return false;
   decoded = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
   return true;
}

bool JournalLookup(string command_id, string &status, string &ticket)
{
   int handle = FileOpen(JOURNAL_FILE, FILE_READ|FILE_CSV|FILE_ANSI|FILE_COMMON, ',');
   if(handle == INVALID_HANDLE) return false;
   bool found = false;
   while(!FileIsEnding(handle))
   {
      string stored_id = FileReadString(handle);
      string stored_status = FileReadString(handle);
      string stored_ticket = FileReadString(handle);
      // Consume message and timestamp together, including any CSV delimiters
      // in a broker message. The next read must start at the next record.
      while(!FileIsEnding(handle) && !FileIsLineEnding(handle)) FileReadString(handle);
      if(stored_id == command_id) { status = stored_status; ticket = stored_ticket; found = true; }
   }
   FileClose(handle);
   return found;
}

void JournalAppend(string command_id, string status, string ticket, string message)
{
   int handle = FileOpen(JOURNAL_FILE, FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON, ',');
   if(handle == INVALID_HANDLE) { PrintFormat("Monatise journal unavailable error=%d", GetLastError()); return; }
   FileSeek(handle, 0, SEEK_END);
   FileWrite(handle, command_id, status, ticket, message, TimeToString(TimeGMT(), TIME_DATE|TIME_SECONDS));
   FileFlush(handle);
   FileClose(handle);
}

void AcknowledgeEvidence(string command_id, string status, string ticket, string message,
                         bool submission_attempted, string broker_retcode,
                         string requested_price, string fill_price, string slippage,
                         string executed_volume, string executed_stop, string executed_target)
{
   string body = "{\"status\":\"" + JsonEscape(status) + "\",\"broker_ticket\":\"" + JsonEscape(ticket)
               + "\",\"broker_retcode\":\"" + JsonEscape(broker_retcode)
               + "\",\"submission_attempted\":" + (submission_attempted ? "true" : "false")
               + ",\"requested_price\":\"" + JsonEscape(requested_price)
               + "\",\"fill_price\":\"" + JsonEscape(fill_price)
               + "\",\"slippage\":\"" + JsonEscape(slippage)
               + "\",\"executed_volume\":\"" + JsonEscape(executed_volume)
               + "\",\"executed_stop_loss\":\"" + JsonEscape(executed_stop)
               + "\",\"executed_take_profit\":\"" + JsonEscape(executed_target)
               + "\",\"message\":\"" + JsonEscape(message) + "\",\"broker_observed_at\":\""
               + IsoTime(TimeGMT()) + "\"}";
   string response; int http_status;
   SignedRequest("POST", "/api/ftmo/bridge/commands/" + command_id + "/ack", body, response, http_status);
}

void Acknowledge(string command_id, string status, string ticket, string message)
{
   AcknowledgeEvidence(command_id, status, ticket, message, false, "", "", "", "", "", "", "");
}

bool GoldPriceGuard(string payload, string symbol, string side, double entry, string &reason)
{
   string gold_symbol, mapping_reason;
   double reference = StringToDouble(JsonString(payload, "price_guard_reference"));
   double allowance = StringToDouble(JsonString(payload, "maximum_adverse_price_deviation"));
   if(JsonString(payload, "gold_price_guard_version") != "1"
      || !ResolveBrokerSymbol("XAUUSD", gold_symbol, mapping_reason) || symbol != gold_symbol
      || (side != "buy" && side != "sell")
      || !MathIsValidNumber(reference) || reference <= 0
      || !MathIsValidNumber(allowance) || allowance <= 0
      || !MathIsValidNumber(entry) || entry <= 0
      || !MathIsValidNumber(InpGoldMaximumAdversePriceDeviation)
      || allowance > InpGoldMaximumAdversePriceDeviation)
      { reason = "Gold price guard is invalid or exceeds local policy"; return false; }
   double adverse = side == "buy" ? entry - reference : reference - entry;
   if(adverse > allowance + 1e-8)
      { reason = "live FTMO price exceeded the approved deviation"; return false; }
   return true;
}

bool FinalOrderValidation(string execution_payload, string &reason, double &validated_price)
{
   if(!InpExecutionEnabled || !InpMasterAccountApproved) { reason = "local execution gates are disabled"; return false; }
   if(!IdentityMatches()) { reason = "account/server/currency mismatch"; return false; }
   if(!TradingPermission()) { reason = "MT5 trading permission is unavailable"; return false; }
   string operation = JsonString(execution_payload, "operation");
   long expires_epoch = StringToInteger(JsonString(execution_payload, "expires_epoch"));
   if(expires_epoch <= 0 || TimeGMT() >= (datetime)expires_epoch) { reason = "execution command has expired"; return false; }
   string target_text = JsonString(execution_payload, "target_id");
   ulong target_id = (ulong)StringToInteger(target_text);
   if(operation != "open")
   {
      if(target_id == 0) { reason = "management target is invalid"; return false; }
      if(operation == "cancel")
      {
         if(!OrderSelect(target_id) || OrderGetInteger(ORDER_MAGIC) != InpMagicNumber) { reason = "order is absent or not owned by Monatise"; return false; }
      }
      else
      {
         if(!PositionSelectByTicket(target_id) || PositionGetInteger(POSITION_MAGIC) != InpMagicNumber) { reason = "position is absent or not owned by Monatise"; return false; }
      }
      return true;
   }
   if(PositionsTotal() + OrdersTotal() >= MathMax(1, InpMaximumOpenExposures))
   {
      reason = "maximum open position/pending-order exposure limit is reached";
      return false;
   }
   string symbol = JsonString(execution_payload, "symbol");
   string side = JsonString(execution_payload, "side");
   string order_type = JsonString(execution_payload, "order_type");
   double volume = StringToDouble(JsonString(execution_payload, "volume"));
   double stop = StringToDouble(JsonString(execution_payload, "stop_loss"));
   double target = StringToDouble(JsonString(execution_payload, "take_profit"));
   MqlTick tick;
   if(symbol == "" || !SymbolInfoTick(symbol, tick)) { reason = "FTMO quote is unavailable"; return false; }
   datetime command_quote_utc = BrokerTimeToUtc(tick.time);
   long command_quote_age = (long)TimeGMT() - (long)command_quote_utc;
   if(command_quote_age < -1 || command_quote_age > 5) { reason = "FTMO quote is stale or clock skew was detected"; return false; }
   double tick_size = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
   double tick_value = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE_LOSS);
   if(tick_value <= 0) tick_value = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
   double entry = order_type == "market" ? ((side == "buy") ? tick.ask : tick.bid) : StringToDouble(JsonString(execution_payload, "entry"));
   validated_price = entry;
   double approved_entry = StringToDouble(JsonString(execution_payload, "entry"));
   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
   double volume_min = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double volume_max = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   double volume_step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   if(tick_size <= 0 || tick_value <= 0 || point <= 0 || volume <= 0) { reason = "symbol specification is invalid"; return false; }
   if(SymbolInfoInteger(symbol, SYMBOL_TRADE_MODE) != SYMBOL_TRADE_MODE_FULL) { reason = "symbol is not fully enabled for trading"; return false; }
   if(volume < volume_min - 1e-8 || volume > volume_max + 1e-8 || volume_step <= 0
      || MathAbs(volume / volume_step - MathRound(volume / volume_step)) > 1e-8)
      { reason = "volume is outside the FTMO symbol specification"; return false; }
   bool gold_guard = JsonString(execution_payload, "gold_price_guard_version") != "";
   if(gold_guard && (order_type != "market" || !GoldPriceGuard(execution_payload, symbol, side, entry, reason))) return false;
   if(!gold_guard && order_type == "market" && approved_entry > 0 && point > 0
      && MathAbs(entry - approved_entry) / point > MathMax(0, InpMaximumDeviationPoints))
      { reason = "live FTMO price exceeded the approved deviation"; return false; }
   if((tick.ask - tick.bid) / tick_size > InpMaximumSpreadTicks) { reason = "spread exceeds policy"; return false; }
   if(order_type == "limit" && ((side == "buy" && entry >= tick.ask) || (side == "sell" && entry <= tick.bid))) { reason = "pending limit price crossed the market"; return false; }
   if(order_type == "stop" && ((side == "buy" && entry <= tick.ask) || (side == "sell" && entry >= tick.bid))) { reason = "pending stop price crossed the market"; return false; }
   if((side == "buy" && !(stop < entry && entry < target)) || (side == "sell" && !(target < entry && entry < stop))) { reason = "SL/TP geometry is invalid at final quote"; return false; }
   if(JsonString(execution_payload, "replacement_for_proposal_id") != ""
      && ((side == "buy" && tick.ask >= target) || (side == "sell" && tick.bid <= target)))
      { reason = "replacement target has already been reached"; return false; }
   double minimum_stop = MathMax((double)SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL),
                                 (double)SymbolInfoInteger(symbol, SYMBOL_TRADE_FREEZE_LEVEL)) * point;
   if(MathAbs(entry - stop) < minimum_stop) { reason = "SL distance is below the FTMO stop/freeze level"; return false; }
   if(order_type != "market" && MathAbs(entry - (side == "buy" ? tick.ask : tick.bid)) < minimum_stop)
      { reason = "pending entry is below the FTMO stop/freeze distance"; return false; }
   double actual_risk = (MathAbs(entry - stop) / tick_size) * tick_value * volume;
   if(gold_guard)
   {
      double budget = StringToDouble(JsonString(execution_payload, "approved_risk_budget"));
      double minimum_rr = StringToDouble(JsonString(execution_payload, "minimum_reward_risk"));
      if(!MathIsValidNumber(budget) || budget <= 0 || !MathIsValidNumber(minimum_rr) || minimum_rr <= 0)
         { reason = "approved Gold risk policy is invalid"; return false; }
      if(actual_risk > budget + 0.01) { reason = "final Gold risk exceeds approved budget"; return false; }
      if(MathAbs(target - entry) / MathAbs(entry - stop) + 1e-8 < minimum_rr)
         { reason = "final Gold reward/risk is below approved policy"; return false; }
      string zone_low = JsonString(execution_payload, "entry_zone_low");
      string zone_high = JsonString(execution_payload, "entry_zone_high");
      if((zone_low != "" && entry < StringToDouble(zone_low)) || (zone_high != "" && entry > StringToDouble(zone_high)))
         { reason = "final Gold price is outside the approved entry zone"; return false; }
   }
   double risk_limit = AccountInfoDouble(ACCOUNT_EQUITY) * MathMin(InpRiskFraction, 0.03);
   if(actual_risk > risk_limit + 0.01) { reason = "final risk exceeds configured limit"; return false; }
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double open_risk = 0.0;
   if(!CurrentOpenRisk(open_risk, reason)) return false;
   double daily_remaining = InpDailyLossLimit - MathMax(0.0, DailyStartEquity() - equity);
   double total_remaining = InpTotalLossLimit - MathMax(0.0, InpInitialAccountBalance - equity);
   if(open_risk + actual_risk > equity * 0.03 + 0.01) { reason = "final total open risk exceeds 3%"; return false; }
   if(open_risk + actual_risk > MathMin(daily_remaining, total_remaining) + 0.01) { reason = "final FTMO loss capacity is insufficient"; return false; }
   return true;
}

bool ResolvePendingOrderExpiration(
   string symbol,
   datetime requested_expiration_utc,
   ENUM_ORDER_TYPE_TIME &order_time,
   datetime &expiration,
   string &reason
)
{
   long modes = SymbolInfoInteger(symbol, SYMBOL_EXPIRATION_MODE);
   if(requested_expiration_utc <= TimeGMT())
   {
      reason = "approved pending-order expiration has already passed";
      return false;
   }
   datetime broker_expiration = (datetime)(
      (long)requested_expiration_utc + BrokerUtcOffsetSeconds()
   );
   if((modes & SYMBOL_EXPIRATION_SPECIFIED) == SYMBOL_EXPIRATION_SPECIFIED)
   {
      order_time = ORDER_TIME_SPECIFIED;
      expiration = broker_expiration;
      return true;
   }
   if((modes & SYMBOL_EXPIRATION_DAY) == SYMBOL_EXPIRATION_DAY)
   {
      order_time = ORDER_TIME_DAY;
      expiration = 0;
      return true;
   }
   if((modes & SYMBOL_EXPIRATION_SPECIFIED_DAY) == SYMBOL_EXPIRATION_SPECIFIED_DAY)
   {
      order_time = ORDER_TIME_SPECIFIED_DAY;
      expiration = broker_expiration;
      return true;
   }
   if((modes & SYMBOL_EXPIRATION_GTC) == SYMBOL_EXPIRATION_GTC)
   {
      order_time = ORDER_TIME_GTC;
      expiration = 0;
      return true;
   }
   reason = "FTMO symbol exposes no supported pending-order expiration mode";
   return false;
}

void ExecuteCommand(string command_json)
{
   string execution_payload = JsonTopLevelObject(command_json, "payload");
   string command_id = JsonString(execution_payload, "command_id");
   if(command_id == "") command_id = JsonString(command_json, "command_id");
   string previous_status, previous_ticket;
   if(command_id == "") return;
   if(execution_payload == "")
   {
      string malformed_reason = "signed command has no top-level execution payload";
      JournalAppend(command_id, "rejected", "", malformed_reason);
      Acknowledge(command_id, "rejected", "", malformed_reason);
      return;
   }
   string operation = JsonString(execution_payload, "operation");
   if(JournalLookup(command_id, previous_status, previous_ticket))
   {
      Acknowledge(command_id, previous_status, previous_ticket, "duplicate delivery reconciled from EA journal");
      return;
   }
   string reason;
   double requested_price = 0;
   if(!FinalOrderValidation(execution_payload, reason, requested_price))
   {
      JournalAppend(command_id, "rejected", "", reason);
      Acknowledge(command_id, "rejected", "", reason);
      return;
   }
   if(!ValidateProfitIntent(execution_payload, reason))
   { JournalAppend(command_id, "rejected", "", reason); Acknowledge(command_id, "rejected", "", reason); return; }
   string symbol = JsonString(execution_payload, "symbol");
   string side = JsonString(execution_payload, "side");
   string order_type = JsonString(execution_payload, "order_type");
   double entry = StringToDouble(JsonString(execution_payload, "entry"));
   double stop = StringToDouble(JsonString(execution_payload, "stop_loss"));
   double target = StringToDouble(JsonString(execution_payload, "take_profit"));
   double volume = StringToDouble(JsonString(execution_payload, "volume"));
   ulong target_id = (ulong)StringToInteger(JsonString(execution_payload, "target_id"));
   datetime pending_expires_at = (datetime)StringToInteger(JsonString(execution_payload, "pending_expires_epoch"));
   string comment = "MNT:" + StringSubstr(command_id, 0, 16);
   ENUM_ORDER_TYPE_TIME pending_order_time = ORDER_TIME_GTC;
   datetime pending_expiration = 0;
   if(operation == "open")
   {
      if(!Trade.SetTypeFillingBySymbol(symbol))
      {
         reason = "FTMO symbol filling policy is unavailable";
         JournalAppend(command_id, "rejected", "", reason);
         Acknowledge(command_id, "rejected", "", reason);
         return;
      }
      if(order_type != "market" && !ResolvePendingOrderExpiration(
         symbol, pending_expires_at, pending_order_time, pending_expiration, reason
      ))
      {
         JournalAppend(command_id, "rejected", "", reason);
         Acknowledge(command_id, "rejected", "", reason);
         return;
      }
   }
   JournalAppend(command_id, "broker_uncertain", "", "submission began; reconcile before any retry");
   if(operation == "partial_close") { ExecutePartialProfit(execution_payload, command_id); return; }
   Trade.SetExpertMagicNumber(InpMagicNumber);
   Trade.SetAsyncMode(false);
   Trade.SetDeviationInPoints(MathMax(0, InpMaximumDeviationPoints));
   if(operation == "open" && order_type == "market" && JsonString(execution_payload, "gold_price_guard_version") == "1")
   {
      double reference = StringToDouble(JsonString(execution_payload, "price_guard_reference"));
      double allowance = StringToDouble(JsonString(execution_payload, "maximum_adverse_price_deviation"));
      double remaining = side == "buy" ? reference + allowance - requested_price : requested_price - (reference - allowance);
      Trade.SetDeviationInPoints((ulong)MathMax(0, MathFloor((remaining + 1e-8) / SymbolInfoDouble(symbol, SYMBOL_POINT))));
   }
   bool ok = false;
   if(operation == "open")
   {
      if(order_type == "market") ok = side == "buy" ? Trade.Buy(volume, symbol, requested_price, stop, target, comment) : Trade.Sell(volume, symbol, requested_price, stop, target, comment);
      else if(order_type == "limit") ok = side == "buy" ? Trade.BuyLimit(volume, entry, symbol, stop, target, pending_order_time, pending_expiration, comment) : Trade.SellLimit(volume, entry, symbol, stop, target, pending_order_time, pending_expiration, comment);
      else if(order_type == "stop") ok = side == "buy" ? Trade.BuyStop(volume, entry, symbol, stop, target, pending_order_time, pending_expiration, comment) : Trade.SellStop(volume, entry, symbol, stop, target, pending_order_time, pending_expiration, comment);
   }
   else if(operation == "close") ok = Trade.PositionClose(target_id);
   else if(operation == "cancel") ok = Trade.OrderDelete(target_id);
   else if(operation == "sl" || operation == "tp" || operation == "breakeven" || operation == "modify_targets")
   {
      if(PositionSelectByTicket(target_id))
      {
         double current_sl = PositionGetDouble(POSITION_SL), current_tp = PositionGetDouble(POSITION_TP);
         double value = StringToDouble(JsonString(execution_payload, "value"));
         if(operation == "sl") current_sl = value;
         if(operation == "tp" || operation == "modify_targets") current_tp = value;
         if(operation == "breakeven") current_sl = PositionGetDouble(POSITION_PRICE_OPEN);
         ok = Trade.PositionModify(target_id, current_sl, current_tp);
      }
   }
   string ticket = IntegerToString((long)(Trade.ResultOrder() > 0 ? Trade.ResultOrder() : Trade.ResultDeal()));
   string result_status = BrokerResultStatus((int)Trade.ResultRetcode(), operation, order_type,
                                             (long)StringToInteger(ticket), Trade.ResultPrice(), Trade.ResultVolume());
   if(!ok && result_status == "reconciled") result_status = "broker_uncertain";
   string message = Trade.ResultRetcodeDescription();
   if(operation == "open" && order_type != "market")
      message += " | pending lifetime " + EnumToString(pending_order_time);
   JournalAppend(command_id, result_status, ticket, message);
   int digits = symbol == "" ? 8 : (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   double fill_price = Trade.ResultPrice();
   AcknowledgeEvidence(
      command_id, result_status, ticket, message,
      true, IntegerToString((long)Trade.ResultRetcode()),
      DoubleToString(requested_price, digits), DoubleToString(fill_price, digits),
      DoubleToString(MathAbs(fill_price - requested_price), digits),
      DoubleToString(Trade.ResultVolume(), 8), DoubleToString(stop, digits), DoubleToString(target, digits)
   );
}

void PollCommands()
{
   if(!InpExecutionEnabled || !InpMasterAccountApproved || !IdentityMatches()) return;
   string response; int status;
   if(!SignedRequest("GET", "/api/ftmo/bridge/commands", "", response, status) || status != 200) return;
   int cursor = 0;
   while(true)
   {
      int marker = StringFind(response, "\"payload_base64\":\"", cursor);
      if(marker < 0) break;
      string tail = StringSubstr(response, marker);
      string encoded = JsonString(tail, "payload_base64");
      string signature = JsonString(tail, "signature");
      string payload;
      if(DecodeBase64(encoded, payload) && HmacSha256(InpBridgeSecret, payload) == signature)
         ExecuteCommand(payload);
      else
         Print("Monatise command signature verification failed; command rejected");
      cursor = marker + 24 + StringLen(encoded);
   }
}

void SendHeartbeat()
{
   string response; int status;
   string body = BuildHeartbeat();
   if(!SignedRequest("POST", "/api/ftmo/bridge/heartbeat", body, response, status)) return;
   if(status != 200)
      PrintFormat("Monatise heartbeat rejected HTTP %d: %s", status, response);
   else
      DynamicSymbols = JsonString(response, "requested_symbols_csv");
}

int OnInit()
{
   MathSrand((int)GetTickCount());
   Trade.SetExpertMagicNumber(InpMagicNumber);
   if(!IdentityMatches())
   {
      Print("Monatise bridge blocked: configured account/server/currency does not match MT5");
      return INIT_FAILED;
   }
   // The server accepts execution quotes for at most five seconds. Keep the
   // outbound heartbeat cadence safely inside that window even when an older
   // chart template retained a larger input value.
   EventSetTimer(MathMax(1, MathMin(InpHeartbeatSeconds, 2)));
   PrintFormat("Monatise FTMO bridge %s started. Execution gate=%s master-approved=%s", EA_VERSION,
               InpExecutionEnabled ? "on" : "off", InpMasterAccountApproved ? "yes" : "no");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
}

void OnTimer()
{
   SendHeartbeat();
   PollCommands();
}

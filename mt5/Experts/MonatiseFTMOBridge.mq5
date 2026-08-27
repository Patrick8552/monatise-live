#property copyright "Monatise"
#property version   "1.06"
#property strict
#property description "Account-bound FTMO bridge. Telegram never talks directly to the broker."

#include <Trade/Trade.mqh>

input string InpControlPlaneUrl        = "https://monatise-live.onrender.com";
input string InpBridgeSecret           = "";       // Set in MT5; never commit the value.
input string InpExpectedAccount        = "";
input string InpExpectedServer         = "FTMO-Server";
input string InpExpectedCurrency       = "USD";
input string InpSymbols                = "XAUUSD,US100.cash,AAPL,EURUSD,GBPUSD,USDJPY,USDCHF,AUDUSD,NZDUSD,USDCAD"; // Non-crypto Telegram preview universe.
input bool   InpExecutionEnabled       = false;    // Independent local gate.
input bool   InpMasterAccountApproved  = false;    // Independent local gate.
input double InpRiskFraction           = 0.03;     // Absolute per-trade ceiling; may be configured lower.
input double InpDailyLossLimit         = 500.0;
input double InpTotalLossLimit         = 1000.0;
input double InpInitialAccountBalance  = 10000.0;
input int    InpMaximumOpenExposures   = 1;        // Positions plus pending orders.
input int    InpHeartbeatSeconds       = 5;
input int    InpHttpTimeoutMs          = 10000;
input int    InpMaximumSpreadTicks     = 80;
input int    InpMaximumDeviationPoints = 20;
input long   InpMagicNumber            = 26082501;

string EA_VERSION = "1.06";
string JOURNAL_FILE = "monatise-ftmo-command-journal.csv";
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

string QuoteJson(string symbol)
{
   MqlTick tick;
   if(!SymbolSelect(symbol, true) || !SymbolInfoTick(symbol, tick) || tick.bid <= 0 || tick.ask <= 0)
      return "";
   datetime observed_utc = TimeGMT();
   datetime broker_time = (datetime)(tick.time_msc / 1000);
   long broker_offset_seconds = BrokerUtcOffsetSeconds();
   datetime broker_time_utc = (datetime)((long)broker_time - broker_offset_seconds);
   long quote_age_seconds = (long)observed_utc - (long)broker_time_utc;
   if(quote_age_seconds < -1 || quote_age_seconds > 5)
      return "";
   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   double tick_size = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
   double tick_value = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE_LOSS);
   if(tick_value <= 0) tick_value = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_value_profit = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE_PROFIT);
   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
   return "\"" + JsonEscape(symbol) + "\":{"
      + "\"bid\":\"" + DoubleToString(tick.bid, digits) + "\","
      + "\"ask\":\"" + DoubleToString(tick.ask, digits) + "\","
      + "\"timestamp\":\"" + IsoTime(observed_utc) + "\","
      + "\"observed_at_utc\":\"" + IsoTime(observed_utc) + "\","
      + "\"quote_observed_at_utc\":\"" + IsoTime(observed_utc) + "\","
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
      + "\"contract_size\":\"" + DoubleToString(SymbolInfoDouble(symbol, SYMBOL_TRADE_CONTRACT_SIZE), 8) + "\","
      + "\"volume_min\":\"" + DoubleToString(SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN), 8) + "\","
      + "\"volume_max\":\"" + DoubleToString(SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX), 8) + "\","
      + "\"volume_step\":\"" + DoubleToString(SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP), 8) + "\","
      + "\"stops_level\":\"" + IntegerToString((int)SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL)) + "\","
      + "\"freeze_level\":\"" + IntegerToString((int)SymbolInfoInteger(symbol, SYMBOL_TRADE_FREEZE_LEVEL)) + "\","
      + "\"trade_mode\":\"" + IntegerToString((int)SymbolInfoInteger(symbol, SYMBOL_TRADE_MODE)) + "\"}";
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
   return true;
}

string BuildHeartbeat()
{
   datetime observed_utc = TimeGMT();
   string quotes = "{";
   string symbols[];
   int count = StringSplit(InpSymbols, ',', symbols);
   for(int index = 0; index < count; index++)
   {
      StringTrimLeft(symbols[index]); StringTrimRight(symbols[index]);
      string quote = QuoteJson(symbols[index]);
      if(quote == "") continue;
      if(quotes != "{") quotes += ",";
      quotes += quote;
   }
   quotes += "}";
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
      + "\"observed_at_utc\":\"" + IsoTime(observed_utc) + "\","
      + "\"broker_time\":\"" + BrokerTime(TimeTradeServer()) + "\","
      + "\"broker_time_offset\":" + IntegerToString((int)BrokerUtcOffsetSeconds()) + ","
      + "\"terminal_local_time\":\"" + BrokerTime(TimeLocal()) + "\","
      + "\"positions\":" + PositionsJson() + ","
      + "\"orders\":" + OrdersJson() + ","
      + "\"quotes\":" + quotes + "}";
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
      FileReadString(handle);
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
                         string requested_price, string fill_price, string slippage,
                         string executed_volume, string executed_stop, string executed_target)
{
   string body = "{\"status\":\"" + JsonEscape(status) + "\",\"broker_ticket\":\"" + JsonEscape(ticket)
               + "\",\"broker_retcode\":\"" + IntegerToString((long)Trade.ResultRetcode())
               + "\",\"requested_price\":\"" + JsonEscape(requested_price)
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
   AcknowledgeEvidence(command_id, status, ticket, message, "", "", "", "", "", "");
}

bool FinalOrderValidation(string payload, string &reason)
{
   if(!InpExecutionEnabled || !InpMasterAccountApproved) { reason = "local execution gates are disabled"; return false; }
   if(!IdentityMatches()) { reason = "account/server/currency mismatch"; return false; }
   if(!TradingPermission()) { reason = "MT5 trading permission is unavailable"; return false; }
   string operation = JsonString(payload, "operation");
   long expires_epoch = StringToInteger(JsonString(payload, "expires_epoch"));
   if(expires_epoch <= 0 || TimeGMT() >= (datetime)expires_epoch) { reason = "execution command has expired"; return false; }
   string target_text = JsonString(payload, "target_id");
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
   string symbol = JsonString(payload, "symbol");
   string side = JsonString(payload, "side");
   string order_type = JsonString(payload, "order_type");
   double volume = StringToDouble(JsonString(payload, "volume"));
   double stop = StringToDouble(JsonString(payload, "stop_loss"));
   double target = StringToDouble(JsonString(payload, "take_profit"));
   MqlTick tick;
   if(symbol == "" || !SymbolInfoTick(symbol, tick)) { reason = "FTMO quote is unavailable"; return false; }
   datetime command_quote_utc = BrokerTimeToUtc(tick.time);
   long command_quote_age = (long)TimeGMT() - (long)command_quote_utc;
   if(command_quote_age < -1 || command_quote_age > 5) { reason = "FTMO quote is stale or clock skew was detected"; return false; }
   double tick_size = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
   double tick_value = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE_LOSS);
   if(tick_value <= 0) tick_value = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
   double entry = order_type == "market" ? ((side == "buy") ? tick.ask : tick.bid) : StringToDouble(JsonString(payload, "entry"));
   double approved_entry = StringToDouble(JsonString(payload, "entry"));
   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
   double volume_min = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double volume_max = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   double volume_step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   if(tick_size <= 0 || tick_value <= 0 || volume <= 0) { reason = "symbol specification is invalid"; return false; }
   if(SymbolInfoInteger(symbol, SYMBOL_TRADE_MODE) != SYMBOL_TRADE_MODE_FULL) { reason = "symbol is not fully enabled for trading"; return false; }
   if(volume < volume_min - 1e-8 || volume > volume_max + 1e-8 || volume_step <= 0
      || MathAbs(volume / volume_step - MathRound(volume / volume_step)) > 1e-8)
      { reason = "volume is outside the FTMO symbol specification"; return false; }
   if(order_type == "market" && approved_entry > 0 && point > 0
      && MathAbs(entry - approved_entry) / point > MathMax(0, InpMaximumDeviationPoints))
      { reason = "live FTMO price exceeded the approved deviation"; return false; }
   if((tick.ask - tick.bid) / tick_size > InpMaximumSpreadTicks) { reason = "spread exceeds policy"; return false; }
   if(order_type == "limit" && ((side == "buy" && entry >= tick.ask) || (side == "sell" && entry <= tick.bid))) { reason = "pending limit price crossed the market"; return false; }
   if(order_type == "stop" && ((side == "buy" && entry <= tick.ask) || (side == "sell" && entry >= tick.bid))) { reason = "pending stop price crossed the market"; return false; }
   if((side == "buy" && !(stop < entry && entry < target)) || (side == "sell" && !(target < entry && entry < stop))) { reason = "SL/TP geometry is invalid at final quote"; return false; }
   double minimum_stop = MathMax((double)SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL),
                                 (double)SymbolInfoInteger(symbol, SYMBOL_TRADE_FREEZE_LEVEL)) * point;
   if(MathAbs(entry - stop) < minimum_stop) { reason = "SL distance is below the FTMO stop/freeze level"; return false; }
   double actual_risk = (MathAbs(entry - stop) / tick_size) * tick_value * volume;
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

void ExecuteCommand(string payload)
{
   string command_id = JsonString(payload, "command_id");
   string operation = JsonString(payload, "operation");
   string previous_status, previous_ticket;
   if(command_id == "") return;
   if(JournalLookup(command_id, previous_status, previous_ticket))
   {
      Acknowledge(command_id, previous_status, previous_ticket, "duplicate delivery reconciled from EA journal");
      return;
   }
   string reason;
   if(!FinalOrderValidation(payload, reason))
   {
      JournalAppend(command_id, "rejected", "", reason);
      Acknowledge(command_id, "rejected", "", reason);
      return;
   }
   string symbol = JsonString(payload, "symbol");
   string side = JsonString(payload, "side");
   string order_type = JsonString(payload, "order_type");
   double entry = StringToDouble(JsonString(payload, "entry"));
   double stop = StringToDouble(JsonString(payload, "stop_loss"));
   double target = StringToDouble(JsonString(payload, "take_profit"));
   double volume = StringToDouble(JsonString(payload, "volume"));
   ulong target_id = (ulong)StringToInteger(JsonString(payload, "target_id"));
   datetime expires_at = (datetime)StringToInteger(JsonString(payload, "expires_epoch"));
   string comment = "MNT:" + StringSubstr(command_id, 0, 16);
   JournalAppend(command_id, "broker_uncertain", "", "submission began; reconcile before any retry");
   Trade.SetExpertMagicNumber(InpMagicNumber);
   Trade.SetAsyncMode(false);
   Trade.SetDeviationInPoints(MathMax(0, InpMaximumDeviationPoints));
   bool ok = false;
   double requested_price = entry;
   if(operation == "open")
   {
      MqlTick execution_tick;
      if(order_type == "market" && SymbolInfoTick(symbol, execution_tick))
         requested_price = side == "buy" ? execution_tick.ask : execution_tick.bid;
      if(order_type == "market") ok = side == "buy" ? Trade.Buy(volume, symbol, 0, stop, target, comment) : Trade.Sell(volume, symbol, 0, stop, target, comment);
      else if(order_type == "limit") ok = side == "buy" ? Trade.BuyLimit(volume, entry, symbol, stop, target, ORDER_TIME_SPECIFIED, expires_at, comment) : Trade.SellLimit(volume, entry, symbol, stop, target, ORDER_TIME_SPECIFIED, expires_at, comment);
      else if(order_type == "stop") ok = side == "buy" ? Trade.BuyStop(volume, entry, symbol, stop, target, ORDER_TIME_SPECIFIED, expires_at, comment) : Trade.SellStop(volume, entry, symbol, stop, target, ORDER_TIME_SPECIFIED, expires_at, comment);
   }
   else if(operation == "close") ok = Trade.PositionClose(target_id);
   else if(operation == "cancel") ok = Trade.OrderDelete(target_id);
   else if(operation == "sl" || operation == "tp" || operation == "breakeven")
   {
      if(PositionSelectByTicket(target_id))
      {
         double current_sl = PositionGetDouble(POSITION_SL), current_tp = PositionGetDouble(POSITION_TP);
         double value = StringToDouble(JsonString(payload, "value"));
         if(operation == "sl") current_sl = value;
         if(operation == "tp") current_tp = value;
         if(operation == "breakeven") current_sl = PositionGetDouble(POSITION_PRICE_OPEN);
         ok = Trade.PositionModify(target_id, current_sl, current_tp);
      }
   }
   string ticket = IntegerToString((long)(Trade.ResultOrder() > 0 ? Trade.ResultOrder() : Trade.ResultDeal()));
   string result_status = ok ? "reconciled" : "rejected";
   string message = Trade.ResultRetcodeDescription();
   JournalAppend(command_id, result_status, ticket, message);
   int digits = symbol == "" ? 8 : (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   double fill_price = Trade.ResultPrice();
   AcknowledgeEvidence(
      command_id, result_status, ticket, message,
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
   if(status != 200) PrintFormat("Monatise heartbeat rejected HTTP %d: %s", status, response);
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
   EventSetTimer(MathMax(1, InpHeartbeatSeconds));
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

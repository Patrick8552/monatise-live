// Signed heartbeat leases authorize local eligibility for at most 20 seconds.
// Native broker expiry is fixed at approval, at most 30 minutes; it is never
// renewed beyond that deadline. Only owned pending orders are deleted.
string PendingKey(string comment, string suffix)
{
   return "MNP." + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)) + "."
      + StringSubstr(Sha256Hex(AccountInfoString(ACCOUNT_SERVER)), 0, 8) + "."
      + StringSubstr(comment, 4) + "." + suffix;
}

bool PreparePendingEntry(string comment, datetime deadline, datetime lease_until)
{
   if(deadline <= TimeGMT() || deadline > TimeGMT() + 1800
      || lease_until <= TimeGMT() || lease_until > TimeGMT() + 20 || lease_until > deadline) return false;
   string key = PendingKey(comment, "expiry");
   if(GlobalVariableCheck(key)) return false; // Includes uncertain submissions.
   if(GlobalVariableSet(key, (double)deadline) == 0) return false;
   if(GlobalVariableSet(PendingKey(comment, "lease"), (double)lease_until) == 0) return false;
   GlobalVariablesFlush();
   return true;
}

bool SelectedManagedPending()
{
   long type = OrderGetInteger(ORDER_TYPE);
   return OrderGetInteger(ORDER_MAGIC) == InpMagicNumber
      && StringFind(OrderGetString(ORDER_COMMENT), "MNP:") == 0
      && (type == ORDER_TYPE_BUY_LIMIT || type == ORDER_TYPE_SELL_LIMIT
          || type == ORDER_TYPE_BUY_STOP || type == ORDER_TYPE_SELL_STOP);
}

void RevokePendingEntry(ulong ticket, string comment)
{
   GlobalVariableSet(PendingKey(comment, "revoked"), 1);
   GlobalVariablesFlush();
   // Risk reduction remains authorized even if new-entry local gates are off.
   if(!IdentityMatches() || !TradingPermission() || !OrderSelect(ticket) || !SelectedManagedPending()) return;
   Trade.SetAsyncMode(false);
   bool sent = Trade.OrderDelete(ticket);
   PrintFormat("Monatise pending cancellation ticket=%I64u sent=%s retcode=%u", ticket, sent ? "true" : "false", Trade.ResultRetcode());
   // Rejected/frozen deletes remain revoked and are retried; native expiry stays.
}

void GuardPendingEntries(bool revoke_all)
{
   if(!IdentityMatches()) return;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0 || !SelectedManagedPending()) continue;
      string comment = OrderGetString(ORDER_COMMENT), key = PendingKey(comment, "expiry");
      string lease_key = PendingKey(comment, "lease");
      datetime expiry = BrokerTimeToUtc((datetime)OrderGetInteger(ORDER_TIME_EXPIRATION));
      if(revoke_all || !InpExecutionEnabled || !InpMasterAccountApproved
         || !GlobalVariableCheck(key) || GlobalVariableGet(key) <= (double)TimeGMT()
         || !GlobalVariableCheck(lease_key) || GlobalVariableGet(lease_key) <= (double)TimeGMT()
         || expiry > (datetime)GlobalVariableGet(key)
         || GlobalVariableCheck(PendingKey(comment, "revoked")) || expiry <= TimeGMT())
         RevokePendingEntry(ticket, comment);
   }
}

void ApplyPendingManifest(string response, string nonce)
{
   string manifest;
   if(!DecodeBase64(JsonString(response, "pending_manifest"), manifest)
      || HmacSha256(InpBridgeSecret, manifest) != JsonString(response, "pending_manifest_signature")
      || JsonString(manifest, "nonce") != nonce
      || JsonString(manifest, "account") != InpExpectedAccount
      || StringCompare(JsonString(manifest, "server"), InpExpectedServer, false) != 0
      || StringCompare(JsonString(manifest, "currency"), InpExpectedCurrency, false) != 0) return;
   long valid_until = StringToInteger(JsonString(manifest, "valid_until"));
   if(valid_until <= (long)TimeGMT() || valid_until > (long)TimeGMT() + 20) return;
   string rows[];
   int count = StringSplit(JsonString(manifest, "leases"), ';', rows);
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0 || !SelectedManagedPending()) continue;
      string comment = OrderGetString(ORDER_COMMENT), key = PendingKey(comment, "expiry");
      long until = 0, deadline = 0;
      for(int j = 0; j < count; j++)
      {
         string pair[];
         if(StringSplit(rows[j], '|', pair) == 3 && (ulong)StringToInteger(pair[0]) == ticket)
         { until = StringToInteger(pair[1]); deadline = StringToInteger(pair[2]); }
      }
      if(!GlobalVariableCheck(key) || GlobalVariableCheck(PendingKey(comment, "revoked"))
         || !InpExecutionEnabled || !InpMasterAccountApproved || until <= (long)TimeGMT()
         || until > valid_until || until > deadline || deadline > (long)GlobalVariableGet(key))
      { RevokePendingEntry(ticket, comment); continue; }
      // Refresh local permission, without repeatedly extending broker lifetime.
      // Earlier source/approval expiry may only shorten the native deadline.
      if(GlobalVariableSet(PendingKey(comment, "lease"), (double)until) == 0
         || GlobalVariableSet(key, (double)deadline) == 0)
      { RevokePendingEntry(ticket, comment); continue; }
      GlobalVariablesFlush();
      datetime current_expiry = BrokerTimeToUtc((datetime)OrderGetInteger(ORDER_TIME_EXPIRATION));
      if(current_expiry <= TimeGMT()) { RevokePendingEntry(ticket, comment); continue; }
      if(current_expiry <= (datetime)deadline) continue;
      if(!IdentityMatches() || !TradingPermission()) continue;
      double entry = OrderGetDouble(ORDER_PRICE_OPEN), sl = OrderGetDouble(ORDER_SL), tp = OrderGetDouble(ORDER_TP);
      if(!Trade.OrderModify(ticket, entry, sl, tp, ORDER_TIME_SPECIFIED, (datetime)(deadline + BrokerUtcOffsetSeconds()), 0)
         || (Trade.ResultRetcode() != TRADE_RETCODE_DONE && Trade.ResultRetcode() != TRADE_RETCODE_NO_CHANGES))
         RevokePendingEntry(ticket, comment);
   }
}

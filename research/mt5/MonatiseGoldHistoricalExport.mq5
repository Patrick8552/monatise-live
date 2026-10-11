// Isolated RESEARCH script. Source only: not installed, compiled or activated.
// Running CopyRates can initiate a broker download. Separate human approval is
// required for the exact account, native symbol and page before running it.
#property strict
#property script_show_inputs
input string InpApprovalReference = "";
input string InpPageId = "";
input long InpExpectedAccount = 0;
input string InpExpectedServer = "";
input string InpNativeSymbol = "";
input string InpTimeframe = "";
input long InpFromBrokerEpoch = 0;
input long InpUntilBrokerEpochExclusive = 0;
input int InpMaximumBars = 240;

string Escape(string value)
{
   StringReplace(value,"\\","\\\\"); StringReplace(value,"\"","\\\"");
   StringReplace(value,"\r","\\r"); StringReplace(value,"\n","\\n");
   return value;
}
string Iso(datetime t)
{
   MqlDateTime v; TimeToStruct(t,v);
   return StringFormat("%04d-%02d-%02dT%02d:%02d:%02dZ",v.year,v.mon,v.day,v.hour,v.min,v.sec);
}
bool HexId(string value)
{
   if(StringLen(value)!=64) return false;
   for(int i=0;i<64;i++)
   {
      ushort c=StringGetCharacter(value,i);
      if(!((c>='0' && c<='9') || (c>='a' && c<='f'))) return false;
   }
   return true;
}
void OnStart()
{
   // No initialization/login, timer, heartbeat, retries, trade or network API.
   if(StringLen(InpApprovalReference)<1 || !HexId(InpPageId)
      || InpExpectedAccount<=0 || InpExpectedServer=="" || InpNativeSymbol==""
      || AccountInfoInteger(ACCOUNT_LOGIN)!=InpExpectedAccount
      || AccountInfoString(ACCOUNT_SERVER)!=InpExpectedServer
      || InpFromBrokerEpoch<=0 || InpUntilBrokerEpochExclusive<=InpFromBrokerEpoch
      || InpUntilBrokerEpochExclusive-InpFromBrokerEpoch>7*86400
      || InpMaximumBars<1 || InpMaximumBars>240)
   { Print("Research export refused: missing exact approved page/identity/range."); return; }
   ENUM_TIMEFRAMES tf;
   int seconds=0;
   if(InpTimeframe=="4h") { tf=PERIOD_H4; seconds=14400; }
   else if(InpTimeframe=="1h") { tf=PERIOD_H1; seconds=3600; }
   else if(InpTimeframe=="15m") { tf=PERIOD_M15; seconds=900; }
   else if(InpTimeframe=="5m") { tf=PERIOD_M5; seconds=300; }
   else if(InpTimeframe=="1m") { tf=PERIOD_M1; seconds=60; }
   else return;
   string canonical=InpNativeSymbol; StringToUpper(canonical);
   if(StringFind(canonical,"XAUUSD")!=0 && StringFind(canonical,"XAU/USD")!=0)
   { Print("Research export refused: broker Gold symbol required."); return; }
   // Bound memory before calling the date-range overload. Plans split closures
   // and historical offset eras; end is exclusive, CopyRates end is inclusive.
   if((InpUntilBrokerEpochExclusive-InpFromBrokerEpoch+seconds-1)/seconds>InpMaximumBars)
   { Print("Research export refused: page span exceeds memory bound."); return; }
   if(!SymbolSelect(InpNativeSymbol,true)) return;
   string file="monatise_gold_"+InpPageId+".json";
   if(FileIsExist(file)) { Print("Research export refused: file already exists."); return; }
   MqlRates rates[]; ArraySetAsSeries(rates,false);
   ResetLastError();
   int copied=CopyRates(InpNativeSymbol,tf,(datetime)InpFromBrokerEpoch,
                        (datetime)(InpUntilBrokerEpochExclusive-1),rates);
   int failure=GetLastError();
   if(copied>InpMaximumBars) { Print("Research export refused: response exceeds page bound."); return; }
   long first=0; SeriesInfoInteger(InpNativeSymbol,tf,SERIES_FIRSTDATE,first);
   string rows="";
   for(int i=0;i<MathMax(0,copied);i++)
   {
      if(i>0) rows+=",";
      rows+="{\"t_broker\":"+IntegerToString((long)rates[i].time)
         +",\"o\":"+StringFormat("%.17g",rates[i].open)
         +",\"h\":"+StringFormat("%.17g",rates[i].high)
         +",\"l\":"+StringFormat("%.17g",rates[i].low)
         +",\"c\":"+StringFormat("%.17g",rates[i].close)
         +",\"v\":"+IntegerToString((long)rates[i].tick_volume)
         +",\"real_volume\":"+IntegerToString((long)rates[i].real_volume)
         +",\"spread_points\":"+IntegerToString(rates[i].spread)+"}";
   }
   long offset=(long)MathRound(((double)TimeTradeServer()-(double)TimeGMT())/60.0)*60;
   double point=SymbolInfoDouble(InpNativeSymbol,SYMBOL_POINT);
   string body="{\"schema\":\"gold-mt5-historical-export-v1\",\"page_id\":\""+InpPageId
      +"\",\"approval_reference\":\""+Escape(InpApprovalReference)
      +"\",\"account_id\":\""+IntegerToString(InpExpectedAccount)
      +"\",\"server\":\""+Escape(AccountInfoString(ACCOUNT_SERVER))
      +"\",\"symbol\":\""+Escape(InpNativeSymbol)+"\",\"timeframe\":\""+InpTimeframe
      +"\",\"from_broker_epoch\":"+IntegerToString(InpFromBrokerEpoch)
      +",\"until_broker_epoch_exclusive\":"+IntegerToString(InpUntilBrokerEpochExclusive)
      +",\"copied_count\":"+IntegerToString(copied)+",\"last_error\":"+IntegerToString(failure)
      +",\"series_first_broker_epoch\":"+IntegerToString(first)
      +",\"captured_at\":\""+Iso(TimeGMT())+"\",\"broker_time_offset\":"+IntegerToString(offset)
      +",\"point\":"+DoubleToString(point,10)
      +",\"tick_size\":"+DoubleToString(SymbolInfoDouble(InpNativeSymbol,SYMBOL_TRADE_TICK_SIZE),10)
      +",\"spread_price\":"+DoubleToString(SymbolInfoInteger(InpNativeSymbol,SYMBOL_SPREAD)*point,10)
      +",\"unit_metadata_scope\":\"CURRENT_CAPTURE_ONLY_NOT_HISTORICAL_CERTIFICATION\",\"rows\":["+rows+"]}";
   int handle=FileOpen(file,FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   if(handle==INVALID_HANDLE) return;
   FileWriteString(handle,body); FileFlush(handle); FileClose(handle);
   Print("Research export complete. Source authenticity/calendar review still required.");
}

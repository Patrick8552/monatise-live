#property strict
#include <Trade/Trade.mqh>
// Read-only diagnostic: OrderCheck only. No orders or account changes.
// Capture the same CTrade request construction used by the bridge, without
// forwarding to CTrade::OrderSend or the broker submission function.
class ExpiryCheckTrade : public CTrade
{
protected:
   virtual bool OrderSend(const MqlTradeRequest &request,MqlTradeResult &result)
   {
      MqlTradeCheckResult check={};
      ResetLastError();
      bool ok=::OrderCheck(request,check);
      PrintFormat("EXPIRY_CAPTURE submitted=false action=%s time_mode=%s expiry=%s server=%s remaining=%d fill=%s ok=%s retcode=%u error=%d comment=%s",
         EnumToString(request.action),EnumToString(request.type_time),TimeToString(request.expiration,TIME_DATE|TIME_SECONDS),
         TimeToString(TimeTradeServer(),TIME_DATE|TIME_SECONDS),(int)(request.expiration-TimeTradeServer()),
         EnumToString(request.type_filling),ok?"true":"false",check.retcode,GetLastError(),check.comment);
      return false;
   }
};
void OnStart()
{
   string s="XAUUSD";
   MqlTick q;
   if(!SymbolInfoTick(s,q)) { Print("EXPIRY_CHECK no quote"); return; }
   MqlTradeRequest r={};
   r.action=TRADE_ACTION_PENDING;
   r.symbol=s;
   r.type=ORDER_TYPE_BUY_LIMIT;
   r.volume=SymbolInfoDouble(s,SYMBOL_VOLUME_MIN);
   int digits=(int)SymbolInfoInteger(s,SYMBOL_DIGITS);
   r.price=NormalizeDouble(q.ask-5,digits);
   r.sl=NormalizeDouble(r.price-5,digits);
   r.tp=NormalizeDouble(r.price+15,digits);
   r.type_time=ORDER_TIME_SPECIFIED;
   long filling=SymbolInfoInteger(s,SYMBOL_FILLING_MODE);
   r.type_filling=(filling & SYMBOL_FILLING_FOK)!=0 ? ORDER_FILLING_FOK : ORDER_FILLING_IOC;
   PrintFormat("EXPIRY_CHECK clocks utc=%s server=%s tick=%s modes=%d positions=%d orders=%d",TimeToString(TimeGMT(),TIME_DATE|TIME_SECONDS),TimeToString(TimeTradeServer(),TIME_DATE|TIME_SECONDS),TimeToString(q.time,TIME_DATE|TIME_SECONDS),(int)SymbolInfoInteger(s,SYMBOL_EXPIRATION_MODE),PositionsTotal(),OrdersTotal());
   int horizons[]={20,60,120,600};
   for(int i=0;i<ArraySize(horizons);i++)
   {
      r.expiration=TimeTradeServer()+horizons[i];
      MqlTradeCheckResult c={};
      ResetLastError();
      bool ok=OrderCheck(r,c);
      PrintFormat("EXPIRY_CHECK seconds=%d expiry=%s ok=%s retcode=%u error=%d comment=%s",horizons[i],TimeToString(r.expiration,TIME_DATE|TIME_SECONDS),ok?"true":"false",c.retcode,GetLastError(),c.comment);
   }
   ExpiryCheckTrade probe;
   probe.SetTypeFillingBySymbol(s);
   datetime utc_lease=TimeGMT()+20;
   datetime broker_expiry=(datetime)((long)utc_lease+(long)TimeTradeServer()-(long)TimeGMT());
   probe.BuyLimit(r.volume,r.price,s,r.sl,r.tp,ORDER_TIME_SPECIFIED,broker_expiry,"EXPIRY_CHECK_ONLY");
   PrintFormat("EXPIRY_CHECK finished positions=%d orders=%d",PositionsTotal(),OrdersTotal());
}

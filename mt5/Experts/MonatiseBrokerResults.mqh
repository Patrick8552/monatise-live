// Pure classification: also compiled by the host-side regression tests.
// CTrade's bool only reports request processing, not broker execution.
string BrokerResultStatus(int code, string operation, string order_type,
                          long ticket, double fill_price, double volume)
{
   if(code == 10009) // TRADE_RETCODE_DONE
   {
      if(operation != "open" || (ticket > 0 &&
         (order_type != "market" || (fill_price > 0 && volume > 0))))
         return "reconciled";
   }
   else if(code == 10008) // TRADE_RETCODE_PLACED
   {
      if(operation == "open" && (order_type == "limit" || order_type == "stop") && ticket > 0)
         return "reconciled";
   }
   else if(code == 10025 && (operation == "sl" || operation == "tp" || operation == "breakeven"))
      return "reconciled"; // TRADE_RETCODE_NO_CHANGES
   switch(code)
   {
      case 10004: case 10006: case 10007: case 10013: case 10014:
      case 10015: case 10016: case 10017: case 10018: case 10019:
      case 10020: case 10021: case 10022: case 10024: case 10026:
      case 10027: case 10029: case 10030: case 10032: case 10033:
      case 10034: case 10035: case 10036: case 10038: case 10040:
      case 10042: case 10043: case 10044: case 10045: case 10046:
         return "rejected";
   }
   // Includes partial fills, timeout/connection errors and unknown codes.
   return "broker_uncertain";
}

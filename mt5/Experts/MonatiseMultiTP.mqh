// Pure validation shared with the native C++ test harness. No order side effects.
bool MultiTPVolumeValid(double volume, double remaining, double minimum, double step)
{
   if(!MathIsValidNumber(volume) || !MathIsValidNumber(remaining)
      || !MathIsValidNumber(minimum) || !MathIsValidNumber(step)
      || step <= 0 || minimum <= 0 || volume < minimum - 1e-8 || volume >= remaining - 1e-8)
      return false;
   return remaining - volume >= minimum - 1e-8
      && MathAbs(volume / step - MathRound(volume / step)) < 1e-8
      && MathAbs((remaining-volume) / step - MathRound((remaining-volume) / step)) < 1e-8;
}

bool MultiTPLevelValid(double entry, double stop, double price, double previous,
                       bool buy, double tick, double minimum_distance, double minimum_rr, double increment_r, bool first)
{
   if(!MathIsValidNumber(entry) || !MathIsValidNumber(stop) || !MathIsValidNumber(price)
      || !MathIsValidNumber(previous) || tick <= 0 || price <= 0 || entry <= 0 || stop <= 0)
      return false;
   double sign = buy ? 1.0 : -1.0;
   double risk = (entry-stop)*sign;
   if(risk <= 0 || (price-entry)*sign < minimum_distance - 1e-8
      || (price-previous)*sign < MathMax(tick, first ? 0.0 : risk*increment_r) - 1e-8)
      return false;
   if(MathAbs(price/tick - MathRound(price/tick)) > 1e-6) return false;
   return !first || (price-entry)*sign / risk >= minimum_rr - 1e-8;
}

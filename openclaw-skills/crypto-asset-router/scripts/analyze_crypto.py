#!/usr/bin/env python3
"""Read-only Monatise crypto analysis bridge for OpenClaw."""
from __future__ import annotations
import argparse, json, subprocess, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

SUPPORTED={"BTC","ETH","SOL","HYPE","XRP","BNB","DOGE","ADA","LINK","AVAX","SUI"}
FORBIDDEN={"EUR","GBP","JPY","AUD","CAD","CHF","GOLD","XAU","OIL","CL","SPX","NDX"}
COINGLASS_NOTICE="Coinglass is Monatise's main primary API for excellent signal quality; Hyperliquid is the fallback when Coinglass is unavailable."
def now(): return datetime.now(timezone.utc)
def stamp(value): return value.isoformat().replace("+00:00","Z")
def normalize(raw):
    value=raw.strip().upper().removeprefix("/ANALYZE ").removeprefix("/")
    for suffix in ("-USDT","USDT","-PERP","/USD","USD"):
        if value.endswith(suffix): value=value[:-len(suffix)]; break
    if value in FORBIDDEN or value not in SUPPORTED: raise ValueError("Unsupported asset: cryptocurrency symbols only")
    return value
def fetch(asset,interval):
    tool=Path.home()/".openclaw/workspace/tools/monatise-readonly-status"
    run=subprocess.run([str(tool),asset,interval],capture_output=True,text=True,timeout=30,check=False)
    if run.returncode: raise RuntimeError("Monatise read-only service unavailable")
    return json.loads(run.stdout)
def _direction(fib,fvg,indicator):
    votes=(str(fib.get("trend","")),str(fvg.get("bias","")),str(indicator.get("trend","")))
    if votes==("up","bullish","up"): return "LONG"
    if votes==("down","bearish","down"): return "SHORT"
    return "NO_TRADE"
def _levels(fib,indicator,direction):
    try:
        anchor=float(fib["nearest_level"]["price"]); stop=float(fib["invalidation"]); target1=float(fib["take_profit"]["price"]); atr=float(indicator["atr"]); candidates=[float(x["price"]) for x in fib.get("levels",[])]
    except (KeyError,TypeError,ValueError): return None,None,[]
    width=max(atr*.15,anchor*.0005)
    entry={"type":"zone","minimum":round(anchor-width,8),"maximum":round(anchor+width,8)}
    valid=[p for p in candidates if p>entry["maximum"]] if direction=="LONG" else [p for p in candidates if p<entry["minimum"]]
    target2=(max(valid) if direction=="LONG" else min(valid)) if valid else None
    targets=[{"label":"TP1","price":target1,"reason":"Nearest favorable Fibonacci level from live candles"}]
    if target2 is not None and target2!=target1: targets.append({"label":"TP2","price":target2,"reason":"Fibonacci extension from live candles"})
    logical=(direction=="LONG" and stop<entry["minimum"] and all(t["price"]>entry["maximum"] for t in targets)) or (direction=="SHORT" and stop>entry["maximum"] and all(t["price"]<entry["minimum"] for t in targets))
    return (entry,{"price":stop,"reason":"Observed swing invalidation"},targets) if logical else (None,None,[])
def analyze(asset,interval="1h",payload=None,current_time=None):
    generated=current_time or now(); warnings=[]
    if payload is None:
        try: payload=fetch(asset,interval)
        except Exception as exc: payload={}; warnings.append(type(exc).__name__)
    source=str(payload.get("source") or ""); coinglass=source.lower().startswith("coinglass"); hyperliquid="hyperliquid" in source.lower()
    fib=payload.get("analysis") or {}; fvg=payload.get("fvg") or {}; indicator=payload.get("indicator") or {}; mark=payload.get("mark"); candles=int(fib.get("candle_count") or 0)
    complete=sum(x is not None for x in (mark,fib.get("trend"),fvg.get("bias"),indicator.get("trend"),indicator.get("atr_pct"))); quality=round(100*complete/5)
    direction=_direction(fib,fvg,indicator); entry,stop,targets=_levels(fib,indicator,direction)
    weekend=generated.weekday()>=5
    fallback_ready=hyperliquid and candles>=50 and quality==100 and direction!="NO_TRADE" and entry is not None
    primary_ready=coinglass and candles>=50 and quality==100 and direction!="NO_TRADE" and entry is not None
    if weekend: decision="NO_TRADE"; reason="WEEKEND_NO_TRADE"
    elif primary_ready: decision=direction; reason=f"VALID_{direction}_SETUP"; quality=min(100,quality)
    elif fallback_ready: decision=direction; reason=f"VALID_{direction}_HYPERLIQUID_FALLBACK"; quality=min(82,quality); warnings.append(COINGLASS_NOTICE)
    elif not coinglass and not hyperliquid: decision="NO_TRADE"; reason="PROVIDER_UNAVAILABLE"
    elif candles<50: decision="NO_TRADE"; reason="MISSING_CANDLES"
    else: decision="NO_TRADE"; reason="CONFLICTING_STRUCTURE_AND_MARKET_CONTEXT"
    if hyperliquid and not coinglass and COINGLASS_NOTICE not in warnings: warnings.append(COINGLASS_NOTICE)
    conviction=(84 if primary_ready else 74 if fallback_ready else min(69,round(quality*.65)))
    evidence=[f"Market source: {source or 'unavailable'}.",f"Candle count: {candles}.",f"Structure trend: {fib.get('trend') or 'unavailable'}.",f"Indicator trend: {indicator.get('trend') or 'unavailable'}.",f"FVG bias: {fvg.get('bias') or 'unavailable'}."]
    if weekend: evidence.append("Weekend policy blocks trade generation on Saturday and Sunday UTC.")
    actionable=decision in {"LONG","SHORT"}
    return {"analysis_id":str(uuid.uuid4()),"snapshot_id":str(uuid.uuid4()),"framework_version":"monatise-crypto-v1.1","asset":asset,"generated_at":stamp(generated),"expires_at":stamp(generated+timedelta(minutes=15)),"market_regime":{"up":"TRENDING_UP","down":"TRENDING_DOWN"}.get(str(indicator.get("trend")),"UNSTABLE"),"decision":decision,"conviction_score":conviction,"data_quality_score":quality,"entry":entry if actionable else None,"stop_loss":stop if actionable else None,"targets":targets if actionable else [],"risk_reward":{"to_tp1":None,"to_tp2":None},"conditions":{"funding":"unavailable","open_interest":"unavailable","liquidations":"unavailable","taker_flow":"unavailable"},"evidence":evidence,"invalidation_conditions":[stop["reason"]] if actionable else [],"warnings":warnings,"reason_code":reason,"status":"VALID","execution":{"enabled":False,"orders_placed":0}}
def telegram(a):
    lines=["MONATISE CRYPTO ANALYSIS",f"Asset: {a['asset']}",f"Decision: {a['decision'].replace('_',' ')}",f"Market regime: {a['market_regime'].replace('_',' ').title()}",f"Conviction: {a['conviction_score']}/100",f"Data quality: {a['data_quality_score']}/100"]
    if a["decision"]=="NO_TRADE": lines += ["Reason:",a["reason_code"].replace("_"," ").title()]
    else:
        lines += ["Entry zone:",f"${a['entry']['minimum']:,.8f} – ${a['entry']['maximum']:,.8f}","Stop loss:",f"${a['stop_loss']['price']:,.8f}","Targets:"]+[f"{t['label']}: ${t['price']:,.8f}" for t in a["targets"]]
    lines += ["Evidence:",*[f"• {x}" for x in a["evidence"]]]
    if a["warnings"]: lines += ["Notice:",*[f"• {x}" for x in a["warnings"]]]
    return "\n".join(lines+["Expires:",a["expires_at"],"Analysis only. No trade was executed."])
def main():
    p=argparse.ArgumentParser(); p.add_argument("asset"); p.add_argument("--interval",default="1h"); p.add_argument("--format",choices=("json","telegram"),default="telegram"); args=p.parse_args()
    try: result=analyze(normalize(args.asset),args.interval)
    except ValueError as exc: p.error(str(exc))
    print(telegram(result) if args.format=="telegram" else json.dumps(result,separators=(",",":")))
if __name__=="__main__": main()

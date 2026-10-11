"""Hypothetical price-path reachability, never fills, P&L or profitability."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta
from math import isfinite
from statistics import median

from monatise.research.broker_xauusd.models import instant, expected_opens
from monatise.research.gold_retrospective import OUTCOME_POLICY


def price_path(record, bars, calendar, *, invalidation=None, quotes=None, quote_source_reference=None):
    """Observe after assessment until expiry/invalidation, without assuming entry.

    OHLC bars straddling decision/expiry are excluded. Same-bar TP/SL is ambiguous.
    Quotes, if supplied, must have unique ordered UTC time/sequence keys and a
    genuine source reference. LONG exits inspect Bid, SHORT exits inspect Ask.
    Quote ordering describes a market path, not an execution fill.
    """
    start,end = instant(record["seed_observed_at"]),instant(record["expiry"])
    if invalidation is not None:
        if invalidation.get("setup_identifier") != record["setup_identifier"]:
            raise ValueError("invalidation must belong to this setup")
        end = min(end,instant(invalidation["at"]))
    entry,stop = float(record["entry"]),float(record["stop"])
    if any(not isfinite(v) or v <= 0 for v in (entry,stop)) or entry == stop or end <= start:
        raise ValueError("valid hypothetical reference geometry/window required")
    long = stop < entry
    sign,risk = (1 if long else -1),abs(entry-stop)
    slots = record["raw_slots"]
    levels = [{"identity":s["identity"],"ratio":s["ratio"],"price":float(s["raw_price"]) if s.get("raw_price") is not None else None,
               "eligible":s.get("eligible",False),
               "candidate_rejection_reason":s.get("rejection_reason"),
               "decision_rejection_reason":s.get("decision_rejection_reason"),
               "rejection_reason":s.get("decision_rejection_reason") or s.get("rejection_reason")} for s in slots]
    if any(s["price"] is not None and (not isfinite(s["price"]) or s["price"] <= 0) for s in levels):
        raise ValueError("finite candidate prices required")
    result = {"policy_id":OUTCOME_POLICY,"setup_identifier":record["setup_identifier"],
        "h1_episode_id":record.get("h1_episode_id"),"start":start.isoformat(),"end":end.isoformat(),
        "invalidation":invalidation,"entry":entry,"stop":stop,"planned_entry_assumed_filled":False,
        "execution_status":"NO_FILL_MODEL", "profitability":None,"data_gaps":[],"partial_bars_excluded":0,
        "price_basis":"ORDERED_BID_ASK_QUOTES" if quotes is not None else "BROKER_OHLC_REFERENCE_PROXY",
        "candidates":[],"mfe_usd":None,"mae_usd":None,"mfe_r":None,"mae_r":None,
        "expiry_observed":False,"stop_observed":False,"ambiguous":False}
    path = []
    if quotes is not None:
        if not quote_source_reference:
            raise ValueError("authentic ordered quote source reference required")
        previous = None
        for quote in quotes:
            at = instant(quote["at"])
            key = (at,quote["sequence"])
            if type(quote["sequence"]) is not int or (previous is not None and key <= previous):
                raise ValueError("unique ordered quote time/sequence required")
            bid,ask = quote["bid"],quote["ask"]
            if any(type(v) not in (float,int) or not isfinite(v) or v <= 0 for v in (bid,ask)) or bid > ask:
                raise ValueError("invalid broker Bid/Ask")
            previous = key
            if start <= at < end:
                value = bid if long else ask
                path.append((at,value,value))
        result["quote_source_reference"] = quote_source_reference
        result["coverage_status"] = "UNATTESTED_QUOTE_STREAM_COMPLETENESS"
        result["expiry_observed"] = False  # Last tick alone never proves complete coverage.
    else:
        selected, seen = [],set()
        for row in bars:
            opened = instant(row["opened_at"])
            close = instant(row["scheduled_close_at"])
            if close != opened+timedelta(minutes=1):
                raise ValueError("native M1 close boundary required")
            if row.get("timeframe") != "1m":
                raise ValueError("outcome candle path must be native M1")
            if opened in seen:
                raise ValueError("duplicate outcome bar")
            seen.add(opened)
            if close <= start or opened >= end:
                continue
            if opened < start or close > end:
                result["partial_bars_excluded"] += 1; continue
            if not calendar.regular_bar(opened,"1m"):
                raise ValueError("outcome candle outside reviewed session")
            c = row["candle"]
            if any(type(c[k]) not in (float,int) or not isfinite(c[k]) for k in ("open","high","low","close")) or not c["low"] <= min(c["open"],c["close"]) <= max(c["open"],c["close"]) <= c["high"]:
                raise ValueError("invalid outcome OHLC")
            selected.append(row)
        selected.sort(key=lambda r:r["opened_at"])
        expected = []
        cursor = start
        while cursor < end:
            boundary = min(cursor+timedelta(days=7),end)
            expected.extend(t for t in expected_opens(calendar,"1m",cursor,boundary) if t+timedelta(minutes=1) <= end)
            cursor = boundary
        actual = {r["opened_at"] for r in selected}
        result["data_gaps"] = [t.isoformat() for t in expected if t.isoformat() not in actual]
        path = [(instant(r["opened_at"]),r["candle"]["low"],r["candle"]["high"]) for r in selected]
        result["coverage_status"] = "COMPLETE_FULL_BAR_SUBWINDOW" if not result["data_gaps"] else "MISSING_PRICE_PATH"
        result["expiry_observed"] = invalidation is None and not result["data_gaps"] and bool(selected) and instant(selected[-1]["scheduled_close_at"]) == end
    if path:
        result["mfe_usd"] = max(0.,max((hi-entry) if long else (entry-lo) for _,lo,hi in path))
        result["mae_usd"] = max(0.,max((entry-lo) if long else (hi-entry) for _,lo,hi in path))
        result["mfe_r"],result["mae_r"] = result["mfe_usd"]/risk,result["mae_usd"]/risk
    first_stop = next((index for index,(_,lo,hi) in enumerate(path) if (lo <= stop if long else hi >= stop)),None)
    result["stop_observed"] = first_stop is not None
    for candidate in levels:
        level = candidate["price"]
        target_index = None if level is None or (level-entry)*sign <= 0 else next((i for i,(_,lo,hi) in enumerate(path) if (hi >= level if long else lo <= level)),None)
        if level is None:
            status = "NO_RAW_CANDIDATE_PRICE"
        elif (level-entry)*sign <= 0:
            status = "WRONG_PROFITABLE_SIDE"
        elif not path:
            status = "NO_OBSERVABLE_PRICE_PATH"
        elif target_index is not None and first_stop is not None and target_index == first_stop and quotes is None:
            status = "AMBIGUOUS_SAME_BAR_TP_SL"; result["ambiguous"] = True
        elif result["data_gaps"] or result["partial_bars_excluded"]:
            status = "INCOMPLETE_PATH_ORDERING_UNKNOWN"
        elif first_stop is not None and (target_index is None or first_stop < target_index):
            status = "STOP_FIRST_PRICE_PATH"
        elif target_index is not None:
            status = "TARGET_TOUCHED_BEFORE_OBSERVED_STOP"
        else:
            status = "NOT_TOUCHED_IN_OBSERVED_WINDOW"
        result["candidates"].append({**candidate,"status":status,"raw_price_touched":target_index is not None,
                                     "target_touch_bar_or_quote":path[target_index][0].isoformat() if target_index is not None else None,
                                     "rr":(level-entry)*sign/risk if level is not None else None})
    result["excursion_interpretation"] = "Observed price excursions from a hypothetical reference; not trade MFE/MAE or fills. Missing coverage makes them lower bounds."
    result["touch_interpretation"] = "Price threshold reached in observed high/low or Bid/Ask; gaps do not prove an exact print or executable fill."
    return result


def summarize(records, outcomes, *, sessions):
    groups = defaultdict(list)
    for row in records:
        groups[row.get("h1_episode_id") or "UNAVAILABLE:"+row["h1_context_id"]].append(row)
    by_outcome = {o["setup_identifier"]:o for o in outcomes}
    def counts(rows):
        side = Counter("long" if float(r["stop"]) < float(r["entry"]) else "short" for r in rows)
        return {"setup_events":len(rows),"bullish_setup_events":side["long"],"bearish_setup_events":side["short"],
            "valid_anchors":sum(r.get("valid_constrained_fib",False) for r in rows),
            "rejected_anchors":sum(not r.get("valid_constrained_fib",False) for r in rows),
            "target_eligibility":dict(Counter(str(r["eligible_target_count"]) for r in rows)),
            "rejection_reasons":dict(Counter(r.get("reason") or "SHADOW_VALID" for r in rows)),
            "raw_candidate_path_status":dict(Counter(c["status"] for r in rows if r["setup_identifier"] in by_outcome for c in by_outcome[r["setup_identifier"]]["candidates"]))}
    def distribution(values):
        values = sorted(float(x) for x in values if x is not None)
        return {"n":len(values),"minimum":min(values) if values else None,"median":median(values) if values else None,"maximum":max(values) if values else None}
    return {"policy_id":OUTCOME_POLICY,"total_historical_sessions":sessions,"setup_level":counts(records),
        "h1_episode_clusters":{k:counts(v) for k,v in sorted(groups.items())},
        "qualified_h1_episode_clusters":sum(not k.startswith("UNAVAILABLE:") for k in groups),
        "ratio_touch_counts":{str(ratio):{"candidate_prices":sum(c["ratio"]==ratio and c["price"] is not None for o in outcomes for c in o["candidates"]),
            "observed_raw_touches":sum(c["ratio"]==ratio and c["raw_price_touched"] for o in outcomes for c in o["candidates"]),
            "same_bar_ambiguity":sum(c["ratio"]==ratio and c["status"]=="AMBIGUOUS_SAME_BAR_TP_SL" for o in outcomes for c in o["candidates"])} for ratio in (1.272,1.414,1.618)},
        "missing_data_exclusions":sum(bool(o["data_gaps"]) or o["mfe_usd"] is None for o in outcomes),
        "stop_first_setup_count":sum(any(c["status"] == "STOP_FIRST_PRICE_PATH" for c in o["candidates"]) for o in outcomes),
        "rr_distribution":distribution(c["rr"] for o in outcomes for c in o["candidates"]),
        "mfe_usd_distribution":distribution(o["mfe_usd"] for o in outcomes),
        "mae_usd_distribution":distribution(o["mae_usd"] for o in outcomes),
        "by_broker_session":{k:counts([r for r in records if r.get("session_id","UNAVAILABLE") == k]) for k in sorted({r.get("session_id","UNAVAILABLE") for r in records})},
        "by_advisory_regime":{k:counts([r for r in records if r.get("advisory_regime","UNAVAILABLE") == k]) for k in sorted({r.get("advisory_regime","UNAVAILABLE") for r in records})},
        "expiry_observed":sum(o["expiry_observed"] for o in outcomes),"ambiguous_outcomes":sum(o["ambiguous"] for o in outcomes),
        "profitability":None,"executed_trades":0,"interpretation":"Research price-path counts only. Rejected/target-independent seeds remain included; cluster counts are not independent trade samples."}

"""Offline price-path comparisons; retains rejected seeds and raw identities."""
from collections import Counter

from monatise.research.broker_xauusd.models import digest, instant
from monatise.research.gold_retrospective.dataset import validate_dataset
from monatise.research.gold_retrospective.outcomes import price_path, summarize


def evaluate(replay, dataset):
    calendar=validate_dataset(dataset)
    if (replay.get("sha256") != digest({k:v for k,v in replay.items() if k!="sha256"})
        or replay.get("dataset_sha256") != dataset["sha256"]
        or replay.get("execution_enabled") is not False or replay.get("pit_verified") is not False):
        raise ValueError("immutable isolated replay/dataset pairing required")
    records=replay["records"]
    bars=[r for r in dataset["rows"] if r["timeframe"]=="1m"]
    outcomes,comparisons=[],[]
    for record in records:
        events=[e for e in replay["invalidations"] if e["setup_identifier"]==record["setup_identifier"]]
        invalidation=min(events,key=lambda e:instant(e["at"])) if events else None
        raw=price_path(record,bars,calendar,invalidation=invalidation)
        outcomes.append(raw)
        canonical=record["canonical"]
        plan=canonical.get("take_profit_plan")
        canonical_slots=[] if plan is None else [{"identity":"CANONICAL:"+t["name"],"ratio":None,
            "raw_price":t["price"],"eligible":True} for t in plan["targets"]]
        final_slots=[{"identity":"F0_RESOLVED:"+t["final_name"],"ratio":None,
            "raw_price":t["final_tp"],"eligible":True} for t in record["targets"]]
        comparisons.append({"setup_identifier":record["setup_identifier"],"h1_episode_id":record["h1_episode_id"],
            "canonical_reasons":canonical.get("reasons"),"canonical_target_plan":plan,
            "canonical_price_path":price_path({**record,"raw_slots":canonical_slots},bars,calendar,invalidation=invalidation),
            "f0_status":record["status"],"f0_reason":record["reason"],"f0_raw_price_path":raw,
            "f0_resolved_targets":record["targets"],
            "f0_resolved_price_path":price_path({**record,"raw_slots":final_slots},bars,calendar,invalidation=invalidation),
            "anchors":record["anchor"],"entry":record["entry"],"stop":record["stop"],"expiry":record["expiry"]})
    # Session denominator is only the reviewed assessment window, including
    # windows with no seed. It is not the entire warm-up candle range.
    start,end=instant(replay["assessment_start"]),instant(replay["assessment_end"])
    sessions=sum(a<end and start<b for a,b in calendar.sessions)
    report={"schema":"gold-retrospective-outcomes-v1","result_class":replay["result_class"],
        "evidence_kind":replay["evidence_kind"],"dataset_sha256":dataset["sha256"],"replay_sha256":replay["sha256"],
        "execution_enabled":False,"pit_verified":False,"profitability":None,
        "summary":summarize(records,outcomes,sessions=sessions),"comparisons":comparisons,
        "invalidation_counts":dict(Counter(e["reason"] for e in replay["invalidations"])),
        "seed_rejection_counts":dict(Counter(e["reason"] for e in replay["seed_rejections"])),
        "decision_exclusions":dict(Counter(e["reason"] for e in replay["admissions"] if e.get("reason"))),
        "missing_m1_decision_times":replay["missing_m1_decision_times"],
        "availability_assumptions":replay["assumption"],"fills_or_cost_model":None}
    report["sha256"]=digest(report)
    return report

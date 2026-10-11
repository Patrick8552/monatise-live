"""Bounded synthetic engineering pilot only; no broker API or credentials.

Run from repository root with the existing test runtime. Outputs refuse overwrite.
"""
import argparse
import asyncio
import json
from datetime import timedelta
from pathlib import Path

from monatise.research.broker_xauusd.models import canonical
from monatise.research.gold_retrospective.benchmark import measure_reads
from monatise.research.gold_retrospective.comparison import evaluate
from monatise.research.gold_retrospective.runner import run_replay, verify_research_checkout
from monatise.research.gold_retrospective.storage import AdmittedResearchStore
from tests.research.test_gold_retrospective import synthetic_replay_dataset
from tests.research.test_broker_xauusd_archive import NOW, add, payload
from tests.research.test_broker_xauusd_postgres import connection, isolated
from tests.research.test_databento_history_postgres import private_postgres


def save(file,value):
    with file.open("x") as f:f.write(canonical(value)+"\n")


async def benchmark(parameters):
    async with await connection(parameters) as c:
        a=isolated(c,"phase4-benchmark-100x60",[NOW])
        for i in range(100):
            at=NOW+timedelta(seconds=i)
            p=payload(a,at=at,request_id=f"synthetic-benchmark-{i}",history=True)
            p["timeframes"]={"1m":p["timeframes"]["1m"][-60:]}
            await add(a,p)
        cutoff=NOW+timedelta(seconds=9)
        baseline=await measure_reads(a,cutoff=cutoff)
        before=await a.batches(cutoff=cutoff)
        a.store=AdmittedResearchStore(c)
        after=await a.batches(cutoff=cutoff)
        selective=await measure_reads(a,cutoff=cutoff)
        assert before==after
        row=await (await c.execute("SELECT pg_total_relation_size('monatise_research_broker_documents') AS bytes")).fetchone()
        return {"evidence_kind":"ENGINEERING_SYNTHETIC","stored_batches":100,"native_rows_per_batch":60,
            "table_total_bytes":row["bytes"],"baseline":baseline,"selective":selective,"exact_read_parity":True,
            "median_ratio_baseline_over_selective":baseline["median_read_seconds"]/selective["median_read_seconds"],
            "new_indexes":0,"new_tables":0,"production_database_accessed":False}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--h1-checkout",required=True);p.add_argument("--output",required=True)
    p.add_argument("--benchmark",action="store_true");args=p.parse_args()
    source=verify_research_checkout(args.h1_checkout);out=Path(args.output)
    out.mkdir(parents=True,exist_ok=False)
    summaries={}
    for name,kwargs in (("long",{}),("short",{"short":True}),("unconfirmed_B",{"forming_b":True}),("origin_latency",{"origin_latency":True})):
        ds=synthetic_replay_dataset(source,**kwargs)
        request={"dataset":ds,"assessment_start":"2026-10-05T15:04:10Z","assessment_end":"2026-10-05T15:04:11Z"}
        save(out/f"{name}-dataset.json",ds);save(out/f"{name}-input.json",request)
        replay=run_replay(out/f"{name}-input.json",out/f"{name}-replay.json",h1_checkout=source)
        outcomes=evaluate(replay,ds);save(out/f"{name}-outcomes.json",outcomes)
        summaries[name]={"diagnostics":replay["diagnostics"],"outcomes":outcomes["summary"],
            "coverage":ds["coverage"],"decision_exclusions":outcomes["decision_exclusions"],
            "dataset_sha256":ds["sha256"],"replay_sha256":replay["sha256"],"outcomes_sha256":outcomes["sha256"]}
    if args.benchmark:
        generator=private_postgres.__wrapped__();parameters=next(generator)
        try:save(out/"benchmark.json",asyncio.run(benchmark(parameters)))
        finally:
            try:next(generator)
            except StopIteration:pass
    save(out/"summary.json",{"result_class":"ENGINEERING_TEST_RESULTS","authentic_broker_records":0,
        "retrospective_market_results":None,"verified_pit_results":None,"cases":summaries,
        "interpretation":"Artificial fixtures prove plumbing/rejections; no market availability, reachability or performance estimate."})
    print(f"Engineering pilot saved to {out}; no authentic market evidence acquired.")


if __name__=="__main__":main()

"""Bounded private PostgreSQL read parity, restart recovery and benchmark."""
import asyncio
import json
import os
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path

from monatise.research.gold_retrospective.storage import AdmittedResearchStore
from monatise.research.gold_retrospective.benchmark import measure_reads
from tests.research.test_broker_xauusd_archive import NOW, START, END, payload, add, archive
from tests.research.test_broker_xauusd_postgres import connection, isolated
from tests.research.test_databento_history_postgres import private_postgres


def test_selective_reader_matches_namespace_reader_orphans_cutoffs_and_restart(private_postgres):
    async def scenario():
        clock=[NOW]
        async with await connection(private_postgres) as c:
            a=isolated(c,"phase4-reader-fixture",clock)
            for i in range(30):
                at=NOW+timedelta(microseconds=100000*i)
                await add(a,payload(a,at=at,request_id=f"fixture-{i}"))
            body=a.prepare(payload(a,request_id="orphan"),evidence_kind="ENGINEERING_SYNTHETIC",source_reference="fixture")
            await a._create("batch:"+body["batch_id"],body)
            cutoff=NOW+timedelta(microseconds=950000)
            expected=await a.batches(cutoff=cutoff)
            baseline=await measure_reads(a,cutoff=cutoff)
            a.store=AdmittedResearchStore(c)
            assert await a.batches(cutoff=cutoff)==expected and len(expected)==10
            assert len(await a.batches(cutoff=NOW))==1
            selective=await measure_reads(a,cutoff=cutoff)
            assert selective["selected_json_bytes"]==baseline["selected_json_bytes"]
            assert not await a.batches(cutoff=NOW-timedelta(microseconds=1))
        async with await connection(private_postgres) as c:
            a=isolated(c,"phase4-reader-fixture",clock);a.store=AdmittedResearchStore(c)
            assert await a.batches(cutoff=cutoff)==expected
    asyncio.run(scenario())


def test_private_database_server_restart_preserves_admitted_hashes(private_postgres):
    clock=[NOW]
    async def write():
        async with await connection(private_postgres) as c:
            a=isolated(c,"phase4-process-restart",clock)
            await add(a,payload(a))
            return await a.batches(cutoff=NOW)
    before=asyncio.run(write())
    cluster=Path(private_postgres["host"]).parent/"cluster"
    env={k:v for k,v in os.environ.items() if not k.startswith("PG")}
    subprocess.run([shutil.which("pg_ctl"),"-D",str(cluster),"-l",str(cluster.parent/"restart.log"),"-m","fast","-w","restart"],
                   env=env,capture_output=True,check=True,timeout=20)
    async def read():
        async with await connection(private_postgres) as c:
            a=isolated(c,"phase4-process-restart",clock);a.store=AdmittedResearchStore(c)
            return await a.batches(cutoff=NOW)
    assert asyncio.run(read())==before


def test_cli_import_and_dataset_use_only_explicit_private_socket(private_postgres,tmp_path):
    from monatise.research.gold_retrospective.cli import main
    from tests.research.test_gold_retrospective import plan,export,units
    async def initialize():
        async with await connection(private_postgres):pass
    asyncio.run(initialize())
    a=archive();page=plan(a)["pages"][0]
    def file(name,value):
        p=tmp_path/name;p.write_text(json.dumps(value));return str(p)
    common=["--identity",file("identity.json",a.identity.__dict__),"--calendar",file("calendar.json",a.calendar_manifest),
        "--local-pg-socket",private_postgres["host"],"--port",str(private_postgres["port"]),
        "--database",private_postgres["dbname"],"--user",private_postgres["user"]]
    q=tmp_path/"import-quality.json"
    main(["archive-import",*common,"--page",file("page.json",page),"--export",file("export.json",export(a,page)),
        "--source-reference","ENGINEERING CLI FIXTURE","--engineering","--output",str(q)])
    assert json.loads(q.read_text())["archive_eligible"]
    from datetime import datetime,timezone
    out=tmp_path/"dataset.json"
    main(["dataset",*common,"--cutoff",datetime.now(timezone.utc).isoformat(),"--start",START.isoformat(),"--end",END.isoformat(),
        "--units",file("units.json",units(a)),"--evidence-kind","ENGINEERING_SYNTHETIC","--output",str(out)])
    ds=json.loads(out.read_text());assert ds["rows"] and not ds["pit_verified"]

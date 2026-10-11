"""Explicit offline research commands. No broker connection/download command."""
import argparse
import asyncio
import json
import os
from pathlib import Path

from monatise.application.gold_sessions import GoldSessionCalendar
from monatise.research.broker_xauusd.archive import BrokerObservationArchive
from monatise.research.broker_xauusd.models import BrokerIdentity, canonical
from monatise.research.gold_retrospective.acquisition import acquisition_plan, import_export, validate_export
from monatise.research.gold_retrospective.comparison import evaluate
from monatise.research.gold_retrospective.dataset import build_dataset
from monatise.research.gold_retrospective.runner import run_replay
from monatise.research.gold_retrospective.storage import AdmittedResearchStore


def load(file,maximum=100_000_000):
    path=Path(file)
    if path.stat().st_size>maximum:raise ValueError("bounded local input required")
    return json.loads(path.read_bytes())


def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("x") as f:f.write(canonical(value)+"\n")


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest="command",required=True)
    for name in ("plan","inspect","archive-import","dataset"):
        p=commands.add_parser(name);p.add_argument("--identity",required=True);p.add_argument("--calendar",required=True);p.add_argument("--output",required=True)
        if name in {"plan","dataset"}:
            p.add_argument("--start",required=True);p.add_argument("--end",required=True)
        if name=="plan":p.add_argument("--mapping-reference",required=True);p.add_argument("--page-bars",type=int,default=240)
        if name in {"inspect","archive-import"}:p.add_argument("--page",required=True);p.add_argument("--export",required=True)
        if name in {"archive-import","dataset"}:
            # Unix socket only. Never read a production DSN or credentials from
            # environment. Existing research schema must already be installed.
            p.add_argument("--local-pg-socket",required=True);p.add_argument("--port",type=int,required=True)
            p.add_argument("--database",required=True);p.add_argument("--user",required=True)
        if name=="archive-import":
            p.add_argument("--source-reference",required=True);p.add_argument("--capture-calendar");p.add_argument("--engineering",action="store_true")
        if name=="dataset":
            p.add_argument("--cutoff",required=True);p.add_argument("--units",required=True);p.add_argument("--source-review")
            p.add_argument("--evidence-kind",required=True,choices=["ENGINEERING_SYNTHETIC","RETROSPECTIVE_HISTORICAL_DOWNLOAD"])
    p=commands.add_parser("replay");p.add_argument("--input",required=True);p.add_argument("--output",required=True);p.add_argument("--h1-checkout",required=True)
    p=commands.add_parser("outcomes");p.add_argument("--replay",required=True);p.add_argument("--dataset",required=True);p.add_argument("--output",required=True)
    args=parser.parse_args(argv)
    if Path(args.output).exists():raise ValueError("fresh immutable output required")
    if args.command=="replay":run_replay(args.input,args.output,h1_checkout=args.h1_checkout);return
    if args.command=="outcomes":save(args.output,evaluate(load(args.replay),load(args.dataset)));return
    identity=BrokerIdentity(**load(args.identity));manifest=load(args.calendar)
    calendar=GoldSessionCalendar.from_manifest(manifest);identity.validate_calendar(calendar)
    if args.command=="plan":
        save(args.output,acquisition_plan(identity,calendar,start=args.start,end=args.end,mapping_reference=args.mapping_reference,page_bars=args.page_bars));return
    if args.command=="inspect":
        # Preparation-only context: no persistence or connection is used.
        class Context:pass
        a=Context();a.identity=identity;a.calendar=calendar
        save(args.output,validate_export(load(args.export,8_000_000),load(args.page),a));return
    async def database_operation():
        import psycopg
        from psycopg.rows import dict_row
        socket=Path(args.local_pg_socket)
        if not socket.is_absolute() or not socket.is_dir() or not (socket/f".s.PGSQL.{args.port}").exists():
            raise ValueError("existing explicit local PostgreSQL Unix socket required")
        if any(k.startswith("PG") for k in os.environ):
            raise ValueError("database command refuses inherited PG environment; use a clean local research shell")
        async with await psycopg.AsyncConnection.connect(host=str(socket),port=args.port,dbname=args.database,user=args.user,
            autocommit=True,row_factory=dict_row,password="",passfile="/dev/null",connect_timeout=5) as c:
            a=BrokerObservationArchive(AdmittedResearchStore(c),identity=identity,calendar_manifest=manifest)
            if args.command=="archive-import":
                return await import_export(a,args.export,load(args.page),source_reference=args.source_reference,
                    capture_calendar_manifest=load(args.capture_calendar) if args.capture_calendar else None,engineering=args.engineering)
            return await build_dataset(a,cutoff=args.cutoff,start=args.start,end=args.end,evidence_kind=args.evidence_kind,
                unit_manifest=load(args.units),source_review=load(args.source_review) if args.source_review else None)
    save(args.output,asyncio.run(database_operation()))


if __name__=="__main__":main()

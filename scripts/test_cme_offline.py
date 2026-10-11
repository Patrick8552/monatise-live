"""Run regression tests with disposable local PostgreSQL/Redis and no credentials.

Uses existing binaries only; installs nothing and touches no production service.
The suite's server smoke test runs in paper mode. Local raw-market-data access is
not needed. Optional frozen H1 checkout is used only by offline fixture tests.
"""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def port():
    with socket.socket() as s:
        s.bind(("127.0.0.1",0))
        return s.getsockname()[1]


def run(*, output, h1_checkout=None):
    root=Path(__file__).resolve().parents[1]
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    path=str(Path(sys.executable).parent)+os.pathsep+"/opt/homebrew/bin:/usr/bin:/bin"
    required={name:shutil.which(name,path=path) for name in ("initdb","pg_ctl","redis-server")}
    if not all(required.values()):raise RuntimeError("existing local PostgreSQL/Redis binaries required")
    with tempfile.TemporaryDirectory(prefix="mon-cme-test-",dir="/tmp") as temporary:
        temp=Path(temporary)
        env={"PATH":path,"LANG":"C","HOME":str(temp),"TMPDIR":str(temp),
             "MONATISE_ENVIRONMENT":"test","PYTHONDONTWRITEBYTECODE":"1"}
        if h1_checkout:env["GC_H1_RESEARCH_CHECKOUT"]=str(Path(h1_checkout).resolve())
        cluster,sockets=temp/"cluster",temp/"socket";sockets.mkdir()
        pg_port,redis_port=port(),port()
        subprocess.run([required["initdb"],"-D",str(cluster),"-A","trust","--no-locale","--encoding=UTF8","-U","cme_test"],
                       env=env,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        started=False;redis=None
        with (output/"redis.log").open("w") as redis_log:
            try:
                subprocess.run([required["pg_ctl"],"-D",str(cluster),"-l",str(output/"postgres.log"),
                    "-o",f"-F -k {sockets} -c listen_addresses='127.0.0.1' -p {pg_port}","-w","start"],
                    env=env,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
                started=True
                redis=subprocess.Popen([required["redis-server"],"--bind","127.0.0.1","--port",str(redis_port),
                    "--save","","--appendonly","no","--dir",str(temp)],env=env,stdout=redis_log,stderr=subprocess.STDOUT)
                import redis as redis_module
                client=redis_module.Redis(host="127.0.0.1",port=redis_port)
                deadline=time.monotonic()+10
                while True:
                    try:
                        if client.ping():break
                    except redis_module.ConnectionError:pass
                    if time.monotonic()>deadline:raise RuntimeError("isolated Redis did not start")
                    time.sleep(.1)
                client.close()
                env.update(MONATISE_TEST_DATABASE_URL=f"postgresql://cme_test@127.0.0.1:{pg_port}/postgres",
                           MONATISE_TEST_REDIS_URL=f"redis://127.0.0.1:{redis_port}/15")
                with (output/"pytest.log").open("w") as log:
                    result=subprocess.run([sys.executable,"-m","pytest","-q","--tb=short",
                        "--junitxml="+str(output/"pytest.xml")],cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=1800)
                print((output/"pytest.log").read_text()[-7000:])
                return result.returncode
            finally:
                if redis:
                    redis.terminate()
                    try:redis.wait(timeout=10)
                    except subprocess.TimeoutExpired:redis.kill();redis.wait()
                if started:
                    subprocess.run([required["pg_ctl"],"-D",str(cluster),"-m","immediate","-w","stop"],
                        env=env,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",required=True,type=Path)
    parser.add_argument("--h1-checkout",type=Path)
    args=parser.parse_args()
    raise SystemExit(run(output=args.output,h1_checkout=args.h1_checkout))

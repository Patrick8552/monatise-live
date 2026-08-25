#!/usr/bin/env python3
"""Out-of-band FTMO control administration.

This intentionally cannot place trades or create commands. It only resets the
durable kill switch after an explicit typed acknowledgement. Do not expose it
through Telegram, OpenClaw, or a public HTTP endpoint.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone

from monatise.application.ftmo_master import FTMOMasterConfiguration


RESET_CONFIRMATION = "I_ACKNOWLEDGE_FTMO_KILL_RESET"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Administer the durable FTMO kill switch")
    result.add_argument("command", choices=("reset-kill",))
    result.add_argument("--confirmation", required=True)
    result.add_argument("--actor", required=True, help="Operator identifier for the audit record")
    return result


def main() -> int:
    arguments = parser().parse_args()
    if arguments.confirmation != RESET_CONFIRMATION:
        raise SystemExit("exact kill-reset confirmation was not supplied")
    configuration = FTMOMasterConfiguration.from_environment(os.environ)
    if not configuration.activation_configured:
        raise SystemExit("FTMO activation configuration is incomplete; kill reset refused")
    database_url = os.environ.get("MONATISE_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("PostgreSQL connection is not configured")

    import psycopg

    now = datetime.now(timezone.utc).isoformat()
    with psycopg.connect(database_url, autocommit=False) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT value, version FROM monatise_application_documents "
                "WHERE namespace=%s AND document_key=%s FOR UPDATE",
                ("ftmo_master_control", "state"),
            )
            row = cursor.fetchone()
            value = dict(row[0]) if row else {"armed_until": None, "armed_by": None}
            value.update({"kill_switch": False, "armed_until": None, "armed_by": None, "updated_at": now})
            if row:
                cursor.execute(
                    "UPDATE monatise_application_documents SET value=%s::jsonb, version=version+1, updated_at=NOW() "
                    "WHERE namespace=%s AND document_key=%s AND version=%s",
                    (json.dumps(value), "ftmo_master_control", "state", row[1]),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("durable kill state changed concurrently")
            else:
                cursor.execute(
                    "INSERT INTO monatise_application_documents(namespace, document_key, value, version) VALUES (%s,%s,%s::jsonb,1)",
                    ("ftmo_master_control", "state", json.dumps(value)),
                )
            cursor.execute(
                "INSERT INTO monatise_application_streams(stream, payload) VALUES (%s,%s::jsonb)",
                ("ftmo_master_audit", json.dumps({
                    "event": "kill_switch_reset_out_of_band",
                    "subject": arguments.actor,
                    "fields": {"armed": False},
                    "observed_at": now,
                })),
            )
        connection.commit()
    print("FTMO durable kill switch reset; execution remains disarmed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

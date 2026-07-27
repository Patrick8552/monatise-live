from __future__ import annotations

import argparse
import sqlite3

import psycopg

from monatise.live.performance import SignalPerformanceStore
from monatise.live.users import UserStore


TABLES = (
    "users",
    "sessions",
    "password_resets",
    "login_codes",
    "credentials",
    "user_settings",
    "login_hints",
    "signal_records",
)


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "select 1 from sqlite_master where type = 'table' and name = ?", (table,)
    ).fetchone() is not None


def migrate(sqlite_path: str, database_url: str) -> dict[str, int]:
    # Initializers create the reviewed production schema before any copy starts.
    UserStore(database_url)
    SignalPerformanceStore(database_url)
    source = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    counts: dict[str, int] = {}
    with source, psycopg.connect(database_url) as destination:
        for table in TABLES:
            if not table_exists(source, table):
                counts[table] = 0
                continue
            columns = [str(row["name"]) for row in source.execute(f"pragma table_info({table})")]
            rows = source.execute(f"select * from {table}").fetchall()
            if not rows:
                counts[table] = 0
                continue
            names = ", ".join(columns)
            placeholders = ", ".join(["%s"] * len(columns))
            updates = ", ".join(f"{column}=excluded.{column}" for column in columns if column != "id")
            conflict_column = "id" if "id" in columns else columns[0]
            query = (
                f"insert into {table} ({names}) values ({placeholders}) "
                f"on conflict ({conflict_column}) do update set {updates}"
            )
            destination.executemany(query, [tuple(row[column] for column in columns) for row in rows])
            counts[table] = len(rows)
        destination.execute(
            "select setval(pg_get_serial_sequence('users', 'id'), coalesce((select max(id) from users), 1), true)"
        )
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy Monatise SQLite data into PostgreSQL without deleting the source.")
    parser.add_argument("sqlite_path")
    parser.add_argument("database_url")
    args = parser.parse_args()
    counts = migrate(args.sqlite_path, args.database_url)
    for table, count in counts.items():
        print(f"{table}: {count}")
    print("Migration complete. The SQLite source was retained for verification and rollback.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

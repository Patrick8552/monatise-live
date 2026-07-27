from __future__ import annotations

import argparse
from monatise.live.migration import migrate_sqlite_to_postgres


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy Monatise SQLite data into PostgreSQL without deleting the source.")
    parser.add_argument("sqlite_path")
    parser.add_argument("database_url")
    args = parser.parse_args()
    counts = migrate_sqlite_to_postgres(args.sqlite_path, args.database_url)
    for table, count in counts.items():
        print(f"{table}: {count}")
    print("Migration complete. The SQLite source was retained for verification and rollback.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

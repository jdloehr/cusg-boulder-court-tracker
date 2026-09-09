#!/usr/bin/env python3
"""
One-time bulk copy of every row from a local SQLite DB into a remote
Postgres DB, in FK-safe order, using batched inserts (few network round
trips) instead of the app's normal one-row-at-a-time upsert path.

Why this exists: seeding a fresh remote database by just pointing
scripts/seed_demo_data.py at DATABASE_URL=<remote> works, but is very slow
-- the docket-pull/news-monitor jobs are written to do a handful of queries
per row (see docs/DATA_SOURCE_FINDINGS.md section 2 on the diff/upsert
heuristic), which is fine locally but turns into thousands of sequential
network round trips against a remote DB. This script instead runs the real
pipeline once against a fast local SQLite file, then bulk-copies the
result over in one pass per table.

Usage:
    python scripts/seed_demo_data.py               # local SQLite, fast (as usual)
    DATABASE_URL=<remote postgres url> \\
        python scripts/migrate_local_to_remote.py   # copy that local DB to remote
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, inspect  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.models import Base  # noqa: E402

LOCAL_SQLITE_URL = f"sqlite:///{Path(__file__).resolve().parent.parent / 'court_tracker.db'}"


def main():
    remote_url = os.environ.get("DATABASE_URL")
    if not remote_url or remote_url.startswith("sqlite"):
        print("Set DATABASE_URL to the remote Postgres URL before running this script.")
        sys.exit(1)

    local_engine = create_engine(LOCAL_SQLITE_URL)
    # connect_timeout: fail fast instead of hanging forever if the network
    # is bad. statement_timeout: same, but for a query that starts fine and
    # then blocks server-side -- e.g. waiting on a lock held by some other
    # orphaned connection, which is exactly what happened the first time
    # this script was run against a real remote database (a prior run's
    # process was killed without cleanly closing its transaction, leaving
    # an "idle in transaction" session holding a table lock).
    remote_engine = create_engine(
        remote_url,
        connect_args={"connect_timeout": 15, "options": "-c statement_timeout=30000"},
    )
    Base.metadata.create_all(bind=remote_engine)  # no-op if tables already exist

    RemoteSession = sessionmaker(bind=remote_engine)
    remote_db = RemoteSession()

    total = 0
    # sorted_tables is already in FK-dependency order (parents before children),
    # so inserting in this order never violates a foreign key.
    with local_engine.connect() as local_conn:
        for table in Base.metadata.sorted_tables:
            rows = [dict(row._mapping) for row in local_conn.execute(table.select())]
            if not rows:
                print(f"  {table.name}: 0 rows, skipping")
                continue
            remote_db.execute(table.delete())  # idempotent re-run: replace, don't duplicate
            for i in range(0, len(rows), 500):
                remote_db.execute(table.insert(), rows[i:i + 500])
            remote_db.commit()
            total += len(rows)
            print(f"  {table.name}: {len(rows)} rows copied")

    remote_db.close()
    print(f"\nDone -- {total} total rows copied to the remote database.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Checks a Postgres database's enum types against the current Python enum
definitions in app/models.py, and reports any drift.

Why this exists -- a real bug caught live during build: adding a new value
to a Python enum used in a `sqlalchemy.Enum(...)` column (e.g. adding
`CourtLocation.colorado_supreme_court`) does NOT retroactively add it to
an already-created Postgres ENUM TYPE. `Base.metadata.create_all()` (what
this project uses instead of a real migration tool -- see
docs/ARCHITECTURE.md) only creates *missing* tables/types; it never runs
`ALTER TYPE ... ADD VALUE` on one that already exists. The test suite
never catches this because it runs against SQLite, which has no native
enum type at all (just a CHECK constraint SQLAlchemy doesn't even always
enforce) -- so this class of bug is invisible until it hits a real
Postgres database, exactly as happened here (a 500 on POST /subscriptions
for the new new_recommendation filter type, immediately after deploying a
model change that added it).

Note: this compares by Python enum *member name*, not `.value` -- that's
what `sqlalchemy.Enum(SomePyEnum)` actually persists to Postgres by
default (only `.value` if the column were built with `values_callable`,
which this project's models don't use). A member name/value pair that
differs (there's exactly one: `AcademicPeriodType.break_ = "break"`, named
with a trailing underscore only because `break` is a Python keyword) is
NOT drift -- comparing by `.value` instead would produce a false positive
here, which is exactly the mistake this script's first draft made.

Usage:
    DATABASE_URL=<postgres url> python scripts/check_enum_drift.py

Fix for real drift: connect with psql (or reuse the pattern below) and run
    ALTER TYPE <type_name> ADD VALUE IF NOT EXISTS '<new_member_name>';
for each missing value, then re-run this script to confirm clean.
"""
import enum
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2  # noqa: E402

from app import models  # noqa: E402


def main():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url or database_url.startswith("sqlite"):
        print("Set DATABASE_URL to a real Postgres URL -- this check is meaningless against "
              "SQLite, which has no native enum type to drift.")
        sys.exit(1)

    conn = psycopg2.connect(database_url, connect_timeout=15)
    cur = conn.cursor()

    py_enums = {}
    for name in dir(models):
        obj = getattr(models, name)
        if isinstance(obj, type) and issubclass(obj, enum.Enum) and obj is not enum.Enum:
            py_enums[name.lower()] = {m.name for m in obj}

    cur.execute("""
        SELECT t.typname, array_agg(e.enumlabel ORDER BY e.enumsortorder)
        FROM pg_type t JOIN pg_enum e ON t.oid = e.enumtypid
        GROUP BY t.typname;
    """)
    db_enums = {row[0]: set(row[1]) for row in cur.fetchall()}
    conn.close()

    clean = True
    for name, py_values in py_enums.items():
        db_values = db_enums.get(name)
        if db_values is None:
            print(f"  {name}: no matching Postgres type yet (table not created there, or a rename) -- skipping")
            continue
        missing_in_db = py_values - db_values
        extra_in_db = db_values - py_values
        if missing_in_db or extra_in_db:
            clean = False
            print(f"DRIFT in {name}: missing_in_db={missing_in_db or '{}'} extra_in_db={extra_in_db or '{}'}")
            for value in missing_in_db:
                print(f"    fix: ALTER TYPE {name} ADD VALUE IF NOT EXISTS '{value}';")

    if clean:
        print("No drift -- every Python enum matches its Postgres type exactly.")
    sys.exit(0 if clean else 1)


if __name__ == "__main__":
    main()

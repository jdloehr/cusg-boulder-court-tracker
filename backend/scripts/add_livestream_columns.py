#!/usr/bin/env python3
"""
Superseded by app/migrations.py, which runs this exact patch
automatically on every backend startup now -- discovered right after
this script was first written that this project's Render plan has no
Shell tab to run a one-off script in, so a manual-only migration had
nowhere to actually run in production. Kept here for local/manual use
(e.g. against a Postgres instance outside this project's own Render
deploy) and as the readable, single-purpose version of what
app/migrations.py's POSTGRES_MIGRATIONS list also does automatically.

Same class of gap as scripts/check_enum_drift.py's problem, but for
columns instead of enum values: Base.metadata.create_all() (this
project's stand-in for real migrations) only creates missing TABLES --
for a table that already exists (hearings, in production), it never runs
ALTER TABLE to add new columns, and it never creates the ENUM TYPE a new
column would need either (that only happens as a side effect of creating
the table itself, which is skipped since it already exists).

Safe to re-run -- checks what already exists before doing anything.

Usage: DATABASE_URL=<postgres url> python scripts/add_livestream_columns.py
(the External Database URL from the Postgres resource's own Info tab in
the Render dashboard, not the web service -- see docs/DEPLOYMENT.md)
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2  # noqa: E402


def main():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url or database_url.startswith("sqlite"):
        print("Set DATABASE_URL to a real Postgres URL -- this migration is meaningless against SQLite.")
        sys.exit(1)

    conn = psycopg2.connect(database_url, connect_timeout=15)
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute("SELECT 1 FROM pg_type WHERE typname = 'livestreamsourcetype';")
    if cur.fetchone() is None:
        cur.execute(
            "CREATE TYPE livestreamsourcetype AS ENUM "
            "('state_portal', 'federal_audio_line', 'scotus_audio', 'none');"
        )
        print("Created type livestreamsourcetype")
    else:
        print("Type livestreamsourcetype already exists, skipping")

    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'hearings' AND column_name IN ('livestream_source_type', 'livestream_url');
    """)
    existing = {row[0] for row in cur.fetchall()}

    if "livestream_source_type" not in existing:
        cur.execute(
            "ALTER TABLE hearings ADD COLUMN livestream_source_type livestreamsourcetype "
            "NOT NULL DEFAULT 'none';"
        )
        print("Added hearings.livestream_source_type")
    else:
        print("hearings.livestream_source_type already exists, skipping")

    if "livestream_url" not in existing:
        cur.execute("ALTER TABLE hearings ADD COLUMN livestream_url VARCHAR(500);")
        print("Added hearings.livestream_url")
    else:
        print("hearings.livestream_url already exists, skipping")

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()

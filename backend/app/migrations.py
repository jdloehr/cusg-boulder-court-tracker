"""
Small, hand-written, idempotent schema patches that run automatically on
every backend startup against Postgres -- covering exactly the gap
`Base.metadata.create_all()` (this project's deliberate stand-in for a
real migration tool -- see docs/ARCHITECTURE.md) leaves open: it only
creates tables/types that don't exist yet. A table that already exists in
production never gets ALTERed to pick up a new column, and the enum type
that new column needs never gets created either (that only happens as a
side effect of creating the table itself, which create_all() skips since
it's already there).

This ran as a one-off manual script the first time this exact class of
bug showed up (`scripts/check_enum_drift.py`, for a Python enum gaining a
new *value*). This module exists because the second occurrence -- Phase-2
Section 2 added `livestream_source_type`/`livestream_url` *columns* to
the pre-existing `hearings` table -- shipped without a manual step being
run first (this project's Render plan has no Shell/one-off-job access to
run one), and every `/api/hearings` request 500'd in production until it
was fixed. Running these automatically at boot means the same mistake
can't happen again regardless of hosting-plan constraints.

Deliberately NOT an auto-diff-the-ORM-against-the-DB engine: each patch
below is hand-written, one per schema change that actually shipped,
same spirit as create_all() itself -- narrow and explicit rather than a
second migration system layered on top of it. When Postgres supports an
"if not exists" form of the DDL needed (ADD COLUMN IF NOT EXISTS since
9.6, ADD VALUE IF NOT EXISTS since 12), that's used directly instead of a
hand-rolled existence check.
"""
from __future__ import annotations

from sqlalchemy import text

# Each statement must be safe to run every single boot, forever, against
# a database already fully migrated -- that's the normal case on every
# deploy after the first. Add new entries here (never edit or remove old
# ones -- they need to stay idempotent-safe for a database that hasn't
# booted since before they were added) alongside whatever model change
# needs them, in the same PR/commit.
POSTGRES_MIGRATIONS = [
    # Phase-2 doc, Section 2 (livestream links): new columns on the
    # pre-existing `hearings` table, needing a brand-new enum type that
    # create_all() never creates on its own since it only touches
    # `hearings` when creating the table from scratch.
    """
    DO $$ BEGIN
        CREATE TYPE livestreamsourcetype AS ENUM
            ('state_portal', 'federal_audio_line', 'scotus_audio', 'none');
    EXCEPTION WHEN duplicate_object THEN NULL; END $$;
    """,
    "ALTER TABLE hearings ADD COLUMN IF NOT EXISTS livestream_source_type "
    "livestreamsourcetype NOT NULL DEFAULT 'none';",
    "ALTER TABLE hearings ADD COLUMN IF NOT EXISTS livestream_url VARCHAR(500);",

    # Phase-3 doc, Section 3 (Justice public profiles): new columns on the
    # pre-existing `admin_users` table. admin_invites and
    # password_reset_tokens are brand-new tables, so create_all() creates
    # those (and any enum types only they use) on its own -- no patch
    # needed, same as ArchiveEntry's table in the Phase-2 round.
    "ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS bio TEXT;",
    "ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS year_or_major VARCHAR(120);",
    "ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS why_care TEXT;",
    "ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS fun_fact VARCHAR(255);",
    "ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS photo_data BYTEA;",
    "ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS photo_content_type VARCHAR(40);",

    # Phase-3 doc, Section 4 (linked names): new column on the
    # pre-existing `archive_entries` table (itself new as of Phase 2, but
    # already live in production by the time this shipped).
    "ALTER TABLE archive_entries ADD COLUMN IF NOT EXISTS submitted_by_justice_id VARCHAR(36) "
    "REFERENCES admin_users(id);",

    # Phase-3 doc, Section 2's explicit "merge now" choice: every Justice
    # account also gets full curation access. New Justices get
    # role='editor' set directly at provisioning (routers/account.py);
    # this is the one-time backfill for the original 7, seeded back in
    # Phase 2 with role=NULL. Written to stay a true no-op on every future
    # boot once applied (WHERE role IS NULL matches nothing the second
    # time), not just "safe to run" -- same idempotence bar as every
    # other statement in this list.
    "UPDATE admin_users SET role = 'editor' WHERE is_justice = true AND role IS NULL;",

    # Phase-4 doc, Section 2.3 (account lockout + 2FA): new columns on the
    # pre-existing `admin_users` table. content_reports (Section 2.5) is a
    # brand-new table, so create_all() handles it on its own.
    "ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS failed_login_attempts INTEGER NOT NULL DEFAULT 0;",
    "ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS locked_until TIMESTAMP;",
    "ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS totp_secret VARCHAR(64);",
    "ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS totp_enabled BOOLEAN NOT NULL DEFAULT false;",
    "ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS totp_backup_code_hashes TEXT;",
]


def run_startup_migrations(engine) -> None:
    """No-op against SQLite (local dev/demo just wipes and recreates the
    file when the schema changes -- see docs/ARCHITECTURE.md). Against
    Postgres, applies every patch above inside one transaction; each
    statement is written to be a true no-op if already applied, so this
    is safe to run on literally every startup, including ones where
    nothing changed."""
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        for statement in POSTGRES_MIGRATIONS:
            conn.execute(text(statement))

#!/usr/bin/env python3
"""
Manual entrypoint for the Google Calendar sync job (calendar-sync doc).
Wire this up to a daily cron/scheduled task in production;
app/jobs/scheduler.py does that automatically when ENABLE_SCHEDULER=1,
and the GitHub Actions cron (.github/workflows/scheduled-jobs.yml) does
it independently against production's database directly.

Needs GOOGLE_CALENDAR_CLIENT_ID, GOOGLE_CALENDAR_CLIENT_SECRET, and
GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY set -- without them, every
connected Justice's sync fails at the token-refresh step, which is
logged and isolated per-connection (see app/jobs/google_calendar_sync.py),
not fatal to the run. A no-op (success, zero connections checked) if no
Justice has connected a calendar yet.

Usage:
    python scripts/run_google_calendar_sync.py
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal, init_db  # noqa: E402
from app.jobs.google_calendar_sync import run_google_calendar_sync  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main():
    init_db()
    db = SessionLocal()
    try:
        job = run_google_calendar_sync(db)
        print(f"google_calendar_sync finished: success={job.success} connections_checked={job.rows_seen} "
              f"synced_ok={job.rows_upserted} error={job.error_message}")
        sys.exit(0 if job.success else 1)
    finally:
        db.close()


if __name__ == "__main__":
    main()

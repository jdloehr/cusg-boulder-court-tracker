#!/usr/bin/env python3
"""
Manual entrypoint for the docket-pull job (Section 2.1 / 2.4). Wire this up
to a daily cron/scheduled task in production; app/jobs/scheduler.py does
that automatically when ENABLE_SCHEDULER=1.

Usage:
    python scripts/run_docket_pull.py                  # live pull
    python scripts/run_docket_pull.py --fixture PATH    # run against a CSV file instead of the network
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal, init_db  # noqa: E402
from app.jobs.docket_pull import run_docket_pull  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", help="Path to a CSV file to parse instead of hitting the live network")
    parser.add_argument("--window-days", type=int, default=None)
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        kwargs = {}
        if args.window_days:
            kwargs["window_days"] = args.window_days
        if args.fixture:
            kwargs["csv_text"] = Path(args.fixture).read_text()
        job = run_docket_pull(db, **kwargs)
        print(f"docket_pull finished: success={job.success} rows_seen={job.rows_seen} "
              f"rows_upserted={job.rows_upserted} error={job.error_message}")
        sys.exit(0 if job.success else 1)
    finally:
        db.close()


if __name__ == "__main__":
    main()

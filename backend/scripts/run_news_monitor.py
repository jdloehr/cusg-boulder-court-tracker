#!/usr/bin/env python3
"""Manual entrypoint for the news-monitoring job (Section 2.2)."""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal, init_db  # noqa: E402
from app.jobs.news_monitor import run_news_monitor  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main():
    init_db()
    db = SessionLocal()
    try:
        job = run_news_monitor(db)
        print(f"news_monitor finished: success={job.success} articles_seen={job.rows_seen} "
              f"processed={job.rows_upserted} error={job.error_message}")
        sys.exit(0 if job.success else 1)
    finally:
        db.close()


if __name__ == "__main__":
    main()

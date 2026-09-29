#!/usr/bin/env python3
"""
Manual entrypoint for the news-search job (Phase 8 doc). Wire this up to
a daily cron/scheduled task in production; app/jobs/scheduler.py does
that automatically when ENABLE_SCHEDULER=1, and the GitHub Actions cron
(.github/workflows/scheduled-jobs.yml) does it independently against
production's database directly.

Needs SEARCH_API_KEY and SEARCH_ENGINE_ID set (a Google Custom Search
API key and Programmable Search Engine ID) -- without them, every
per-hearing search fails at the HTTP layer, which is logged and isolated
per-hearing (see app/jobs/news_search.py), not fatal to the run.

Usage:
    python scripts/run_news_search.py
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal, init_db  # noqa: E402
from app.jobs.news_search import run_news_search  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main():
    init_db()
    db = SessionLocal()
    try:
        job = run_news_search(db)
        print(f"news_search finished: success={job.success} hearings_checked={job.rows_seen} "
              f"mentions_created_or_updated={job.rows_upserted} error={job.error_message}")
        sys.exit(0 if job.success else 1)
    finally:
        db.close()


if __name__ == "__main__":
    main()

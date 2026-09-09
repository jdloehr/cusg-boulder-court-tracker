"""
Section 8 / 11: wires the docket-pull and news-monitoring jobs to run daily,
and the digest to run weekly, via APScheduler's BackgroundScheduler.

This process model (an in-process scheduler inside the API server) is fine
for CUSG's scale (Section 7: "any transactional provider's free tier is
almost certainly sufficient"); a higher-traffic deploy would move these to
a separate worker/cron process instead. Started from main.py's startup
event; see run_docket_pull.py / run_news_monitor.py for one-off manual runs.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db import SessionLocal
from app.jobs.digest import run_weekly_digest
from app.jobs.docket_pull import run_docket_pull
from app.jobs.news_monitor import run_news_monitor

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _run_with_session(fn) -> None:
    db = SessionLocal()
    try:
        fn(db)
    except Exception:  # noqa: BLE001 - job functions already alert + log internally
        logger.exception("Scheduled job raised")
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    scheduler = BackgroundScheduler()
    # Daily docket re-pull, early morning (Section 8: "daily re-pull minimum").
    scheduler.add_job(lambda: _run_with_session(run_docket_pull),
                       CronTrigger(hour=5, minute=0), id="docket_pull_daily")
    # Daily news poll, staggered after the docket pull so new hearings exist
    # to match against.
    scheduler.add_job(lambda: _run_with_session(run_news_monitor),
                       CronTrigger(hour=5, minute=30), id="news_monitor_daily")
    # Weekly digest (Section 5.3 default cadence).
    scheduler.add_job(lambda: _run_with_session(run_weekly_digest),
                       CronTrigger(day_of_week="mon", hour=8, minute=0), id="weekly_digest")

    scheduler.start()
    _scheduler = scheduler
    logger.info("Scheduler started: docket_pull(daily 05:00), news_monitor(daily 05:30), "
                "weekly_digest(mon 08:00)")
    return scheduler

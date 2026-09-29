"""
Phase 8 doc: daily call-count tracking for a metered external API
(currently just Google Custom Search, used by app/jobs/news_search.py).

Deliberately a real DB row, not an in-memory counter like
app/rate_limit.py's -- that module's own docstring documents exactly why
it can't be reused here: it's process-local and doesn't survive a
restart or share state across processes, and the job that calls the
search API runs as a separate GitHub Actions process, not the always-on
backend. A persisted row is the only thing both processes (and any local
manual run) can agree on.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.alerting import alert_quota_warning
from app.config import SEARCH_API_ALERT_THRESHOLD, SEARCH_API_DAILY_QUOTA
from app.models import ExternalApiUsage


def record_usage(db: Session, api_name: str, now: datetime) -> ExternalApiUsage:
    """Call once per actual outbound request to the named API (including
    retried attempts -- each one is a real billed/counted call).

    Read-then-write, not a dialect-specific atomic upsert: this only ever
    runs from one GitHub Actions job process at a time (confirmed: this
    job isn't scheduled to run concurrently with itself), so a real
    ON CONFLICT DO UPDATE would be defending against a race that can't
    occur at this project's actual scale -- same reasoning app/rate_limit.py
    documents for its own simpler-than-textbook-correct approach. If this
    job is ever parallelized, swap this for a real upsert."""
    today = now.date()
    row = db.query(ExternalApiUsage).filter_by(api_name=api_name, usage_date=today).first()
    if row is None:
        row = ExternalApiUsage(api_name=api_name, usage_date=today, query_count=0)
        db.add(row)
        db.flush()
    row.query_count += 1
    _maybe_alert(row)
    db.commit()
    return row


def _maybe_alert(row: ExternalApiUsage) -> None:
    """Fires the quota-approaching alert exactly once per UTC day: only
    when query_count has just reached the threshold AND no alert has
    been sent yet today. Every later increment that same day sees
    alert_sent_at already set and skips re-firing -- without this, a job
    that makes 15 more calls after crossing the threshold would send 15
    emails, which defeats the point of an alert."""
    if row.query_count >= SEARCH_API_ALERT_THRESHOLD and row.alert_sent_at is None:
        alert_quota_warning(row.api_name, row.query_count, SEARCH_API_DAILY_QUOTA)
        row.alert_sent_at = datetime.utcnow()

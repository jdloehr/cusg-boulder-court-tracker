"""
Calendar-sync doc: replaces manual AvailabilitySlot entry with a real
Google Calendar for any Justice who's connected one
(GoogleCalendarConnection, app/routers/google_calendar.py handles the
OAuth flow itself -- this module is just the recurring sync).

Two outputs per synced Justice, both derived from one freeBusy.query
call for the current docket window (GOOGLE_CALENDAR_SYNC_WINDOW_DAYS):
1. AvailabilityOverride rows -- the real, date-specific source of truth
   the per-hearing meter and the month view's day-gauge read first (see
   app/availability_slots.py::resolve_free_slots_for_date).
2. A conservative recurring AvailabilitySlot baseline (a (weekday, slot)
   is free only if free on *every* occurrence of that weekday within
   the synced window) -- purely so the pre-existing Team Availability
   weekly heatmap, which has no concept of a specific date at all,
   doesn't go misleadingly blank for a Justice who no longer has any
   manually-painted cells. An approximation by nature; the override
   rows above are the real data for anything date-specific.

Run manually via scripts/run_google_calendar_sync.py, or on a schedule
via APScheduler + the GitHub Actions cron -- same dual-registration
pattern as docket_pull/news_search (app/jobs/scheduler.py).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.orm import Session

from app.alerting import alert_job_failure
from app.availability import NUM_SLOTS, SLOT_MINUTES, SLOT_WINDOW_START_MIN, weekday_abbr
from app.availability_slots import replace_owner_overrides_for_window, replace_owner_slots
from app.config import (
    GOOGLE_CALENDAR_CLIENT_ID,
    GOOGLE_CALENDAR_CLIENT_SECRET,
    GOOGLE_CALENDAR_SYNC_WINDOW_DAYS,
)
from app.models import AvailabilityOwnerType, GoogleCalendarConnection, JobRun
from app.schemas import AvailabilityCell
from app.token_encryption import decrypt_refresh_token

logger = logging.getLogger(__name__)

JOB_NAME = "google_calendar_sync"
MOUNTAIN_TZ = ZoneInfo("America/Denver")  # matches scheduler.py's own cron timezone


def _refresh_access_token(refresh_token: str) -> str:
    """Exchanges a stored refresh token for a fresh access token. Never
    requests a new refresh token here -- only the initial OAuth consent
    (app/routers/google_calendar.py, with prompt=consent) ever issues
    one; a revoked/expired refresh token surfaces as a non-200 here,
    which the caller treats as a sync failure, not a crash."""
    resp = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": GOOGLE_CALENDAR_CLIENT_ID,
            "client_secret": GOOGLE_CALENDAR_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=15,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Token refresh failed ({resp.status_code}): {resp.text}")
    return resp.json()["access_token"]


def _query_freebusy(access_token: str, calendar_id: str, time_min: datetime, time_max: datetime) -> list[tuple[datetime, datetime]]:
    """freeBusy.query only -- the one endpoint this feature's entire
    privacy promise rests on. Never calls events.list or anything else
    that could return event content; the calendar.freebusy OAuth scope
    wouldn't even authorize that."""
    resp = httpx.post(
        "https://www.googleapis.com/calendar/v3/freeBusy",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "timeMin": time_min.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "timeMax": time_max.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "items": [{"id": calendar_id}],
        },
        timeout=15,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"freeBusy query failed ({resp.status_code}): {resp.text}")
    data = resp.json()
    cal = data.get("calendars", {}).get(calendar_id, {})
    if cal.get("errors"):
        raise RuntimeError(f"freeBusy query returned a calendar error: {cal['errors']}")
    busy = []
    for block in cal.get("busy", []):
        start = datetime.fromisoformat(block["start"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(block["end"].replace("Z", "+00:00"))
        busy.append((start, end))
    return busy


def _slot_bounds_local(d: date, slot_index: int) -> tuple[datetime, datetime]:
    """This slot's [start, end) as real, timezone-aware Mountain Time
    instants on this specific date -- not just minutes-since-midnight,
    since a real busy interval from Google is a real UTC instant that
    has to be compared against a real local wall-clock time on a real
    day, DST included."""
    minute_offset = SLOT_WINDOW_START_MIN + slot_index * SLOT_MINUTES
    start = datetime.combine(d, time(0, 0), tzinfo=MOUNTAIN_TZ) + timedelta(minutes=minute_offset)
    return start, start + timedelta(minutes=SLOT_MINUTES)


def compute_free_slots_by_date(
    busy_intervals_utc: list[tuple[datetime, datetime]], date_from: date, date_to: date,
) -> dict[date, set[int]]:
    """For every date in [date_from, date_to], which of the fixed 26
    7am-8pm Mountain Time slots are free -- a slot is free unless it
    overlaps a real busy interval from Google, compared in real
    timezone-aware instants (converting the slot's local wall-clock
    bounds, not the other way around, since a busy interval can only be
    trusted as the real UTC instant Google gave us)."""
    result: dict[date, set[int]] = {}
    d = date_from
    while d <= date_to:
        free_slots = set()
        for slot_index in range(NUM_SLOTS):
            slot_start, slot_end = _slot_bounds_local(d, slot_index)
            is_busy = any(busy_start < slot_end and slot_start < busy_end for busy_start, busy_end in busy_intervals_utc)
            if not is_busy:
                free_slots.add(slot_index)
        result[d] = free_slots
        d += timedelta(days=1)
    return result


def derive_recurring_baseline(free_slots_by_date: dict[date, set[int]]) -> list[AvailabilityCell]:
    """Conservative: a (weekday, slot) only makes it into the baseline
    if it was free on *every* occurrence of that weekday within the
    synced window -- one real one-off meeting on a single Tuesday
    should not make a Justice look permanently unavailable every
    Tuesday on the legacy weekly heatmap, but a slot that's never once
    free across the whole window definitely shouldn't show as free
    there either."""
    occurrences_by_weekday: dict[str, list[date]] = {}
    for d in free_slots_by_date:
        occurrences_by_weekday.setdefault(weekday_abbr(d), []).append(d)

    cells: list[AvailabilityCell] = []
    for wd, dates in occurrences_by_weekday.items():
        common_free: Optional[set[int]] = None
        for d in dates:
            common_free = set(free_slots_by_date[d]) if common_free is None else (common_free & free_slots_by_date[d])
        for slot_index in (common_free or set()):
            cells.append(AvailabilityCell(day_of_week=wd, slot_index=slot_index))
    return cells


@dataclass
class SyncOutcome:
    status: str  # "ok" | "error"
    error: Optional[str] = None


def sync_one_connection(db: Session, connection: GoogleCalendarConnection, now: datetime) -> SyncOutcome:
    """Never raises -- any exception is caught and returned as
    SyncOutcome(status="error"), so one Justice's revoked token can't
    stop every other Justice's sync from running (same per-item
    isolation as app/jobs/news_search.py::search_for_hearing)."""
    try:
        refresh_token = decrypt_refresh_token(connection.encrypted_refresh_token)
        access_token = _refresh_access_token(refresh_token)

        date_from = now.date()
        date_to = date_from + timedelta(days=GOOGLE_CALENDAR_SYNC_WINDOW_DAYS)
        time_min, _ = _slot_bounds_local(date_from, 0)
        _, time_max = _slot_bounds_local(date_to, NUM_SLOTS - 1)

        busy_intervals = _query_freebusy(access_token, connection.calendar_id, time_min, time_max)
        free_slots_by_date = compute_free_slots_by_date(busy_intervals, date_from, date_to)

        replace_owner_overrides_for_window(
            db, AvailabilityOwnerType.justice, connection.admin_user_id, date_from, date_to, free_slots_by_date,
        )
        replace_owner_slots(
            db, AvailabilityOwnerType.justice, connection.admin_user_id, derive_recurring_baseline(free_slots_by_date),
        )

        connection.last_synced_at = now
        connection.last_sync_error = None
        return SyncOutcome(status="ok")
    except Exception as exc:  # noqa: BLE001 -- per-connection isolation, see docstring
        # Doc's own ask: "don't let a broken sync silently zero out their
        # availability" -- the error is recorded, but existing override/
        # recurring rows from the last successful sync are left exactly
        # as they were (no delete/replace call happens above on this path).
        logger.warning("google_calendar_sync: sync failed for admin_user %s: %s", connection.admin_user_id, exc)
        connection.last_sync_error = str(exc)
        return SyncOutcome(status="error", error=str(exc))


def run_google_calendar_sync(db: Session, now: datetime | None = None) -> JobRun:
    now = now or datetime.utcnow()
    job_run = JobRun(job_name=JOB_NAME, started_at=now)
    db.add(job_run)
    db.flush()

    try:
        connections = db.query(GoogleCalendarConnection).all()
        checked = ok = errors = 0
        for connection in connections:
            checked += 1
            outcome = sync_one_connection(db, connection, now)
            if outcome.status == "ok":
                ok += 1
            else:
                errors += 1

        job_run.rows_seen = checked
        job_run.rows_upserted = ok
        job_run.success = True
        job_run.finished_at = datetime.utcnow()
        db.commit()

        logger.info("google_calendar_sync: %d connections checked, %d synced, %d errors", checked, ok, errors)
        # Low-urgency, matching news_search's own severity choice -- a
        # sync failure degrades to last-known-good data, it doesn't take
        # the site down.
        if checked > 0 and errors == checked:
            alert_job_failure(JOB_NAME, f"All {checked} Google Calendar syncs failed this run", severity="low")

        return job_run
    except Exception as exc:  # noqa: BLE001 - job boundary, mirrors docket_pull.py's pattern
        db.rollback()
        job_run.success = False
        job_run.error_message = str(exc)
        job_run.finished_at = datetime.utcnow()
        db.add(job_run)
        db.commit()
        alert_job_failure(JOB_NAME, str(exc), severity="low")
        raise

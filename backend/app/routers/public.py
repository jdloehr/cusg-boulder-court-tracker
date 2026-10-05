"""
Public, unauthenticated endpoints (Section 5.1, 5.2, 5.3). Fully public
browsing, per Section 7: "none required to browse."
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.academic_calendar import current_period
from app.availability import parse_duration_minutes, parse_hearing_time
from app.availability_slots import load_owner_cells, replace_owner_slots
from app.config import REFRESH_COOLDOWN_MINUTES
from app.jobs.google_calendar_sync import MOUNTAIN_TZ
from app.db import SessionLocal, get_db
from app.jobs.docket_pull import run_docket_pull
from app.learn import learn_topic_out, matching_learn_topics
from app.moderation import is_likely_spam_or_profane
from app.rate_limit import check_rate_limit, client_ip
from app.models import (
    AppearanceType,
    AvailabilityOwnerType,
    CaseCategory,
    CommunitySubmission,
    CourtLocation,
    Hearing,
    HearingStatus,
    HearingTypeCategory,
    JobRun,
    NewsMention,
    Subscription,
)
from app.schemas import (
    AcademicCalendarPeriodOut,
    CommunitySubmissionIn,
    DataStatusOut,
    HearingOut,
    SubscriptionCreate,
    SubscriptionOut,
)

router = APIRouter(prefix="/api", tags=["public"])


@router.get("/hearings", response_model=list[HearingOut])
def list_hearings(
    db: Session = Depends(get_db),
    hearing_type_category: Optional[HearingTypeCategory] = None,
    has_news: Optional[bool] = None,
    case_category: Optional[CaseCategory] = None,
    court_location: Optional[CourtLocation] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    show_all_types: bool = False,
):
    """Default (no filters given): Section 5.1's default view -- jury trial
    / oral argument-motions, in-person, next 14 days, plus anything with a
    news mention regardless of type. Pass show_all_types=true or explicit
    filters to broaden."""
    today = date.today()
    q = db.query(Hearing).filter(
        Hearing.is_excluded.is_(False),
        Hearing.status != HearingStatus.cancelled,
    )

    q = q.filter(Hearing.date >= (date_from or today))
    q = q.filter(Hearing.date <= (date_to or today + timedelta(days=14)))

    if hearing_type_category:
        q = q.filter(Hearing.hearing_type_category == hearing_type_category)
    if case_category:
        q = q.filter(Hearing.case_category == case_category)
    if court_location:
        q = q.filter(Hearing.court_location == court_location)

    # Sorted in Python, not SQL: `time` is free text ("9:00 AM", "10:30
    # AM", ...), and ORDER BY on that column sorts alphabetically, not
    # chronologically -- see Hearing.time_sort_key's docstring for the
    # real bug this was.
    hearings = sorted(q.order_by(Hearing.date).all(), key=lambda h: (h.date, h.time_sort_key))

    if hearing_type_category or case_category or show_all_types:
        filtered = hearings
    else:
        filtered = [
            h for h in hearings
            if h.hearing_type_category in (HearingTypeCategory.jury_trial, HearingTypeCategory.oral_argument_motions)
            and h.appearance_type == AppearanceType.in_person
            or h.has_news_mention
        ]

    if has_news is True:
        filtered = [h for h in filtered if h.has_news_mention]
    elif has_news is False:
        filtered = [h for h in filtered if not h.has_news_mention]

    return [_with_learn_topics(HearingOut.from_orm_hearing(h), h, db) for h in filtered]


@router.get("/hearings/{hearing_id}", response_model=HearingOut)
def get_hearing(hearing_id: str, db: Session = Depends(get_db)):
    hearing = db.query(Hearing).filter(Hearing.id == hearing_id).first()
    if not hearing:
        raise HTTPException(404, "Hearing not found")
    return _with_learn_topics(HearingOut.from_orm_hearing(hearing), hearing, db)


def _with_learn_topics(hearing_out: HearingOut, hearing: Hearing, db: Session) -> HearingOut:
    """Phase 9 doc: LearnTopic matches by hearing_type_category/
    case_category, not a stored FK (see app/learn.py), so -- unlike
    news_mentions/community_submissions/teaching_notes, which are real
    relationships HearingOut.from_orm_hearing() already picks up via
    field_validator -- this has to be set explicitly after construction."""
    hearing_out.learn_topics = [learn_topic_out(t) for t in matching_learn_topics(db, hearing)]
    return hearing_out


@router.post("/hearings/{hearing_id}/submissions", status_code=201)
def submit_community_details(hearing_id: str, payload: CommunitySubmissionIn, request: Request,
                              db: Session = Depends(get_db)):
    """Let a visitor add details (a case summary, a judge's name, etc.)
    they know about a hearing. Not published immediately -- goes to the
    admin review queue (Section 4's guardrails apply to visitor-submitted
    content just as much as to the automated pipelines; see
    docs/EXCLUSION_LOGIC.md). An Editor approving it is what actually
    updates the public-facing Hearing.judge_name or surfaces the summary.

    Phase-4 doc, Section 2.2/2.5: rate-limited and spam-filtered like
    every other public write path now, even though this one already sits
    behind a review queue -- keeps the queue itself from filling up with
    obvious spam an Editor then has to manually clear."""
    if not check_rate_limit(f"community-submission:{client_ip(request)}", max_requests=5, window_seconds=600):
        raise HTTPException(429, "Too many submissions from this address -- try again in a few minutes.")

    hearing = db.query(Hearing).filter(Hearing.id == hearing_id).first()
    if not hearing:
        raise HTTPException(404, "Hearing not found")

    if payload.website:  # honeypot tripped -- pretend success, do nothing
        return {"status": "received"}

    if not (payload.summary_text or "").strip() and not (payload.judge_name or "").strip():
        raise HTTPException(400, "Provide a summary, a judge's name, or both")

    for field, value in (("summary_text", payload.summary_text), ("judge_name", payload.judge_name)):
        if is_likely_spam_or_profane(value or ""):
            raise HTTPException(400, f"{field} looks like spam -- please rewrite it")

    submission = CommunitySubmission(
        hearing_id=hearing.id,
        summary_text=(payload.summary_text or "").strip() or None,
        judge_name=(payload.judge_name or "").strip() or None,
        submitter_context=(payload.submitter_context or "").strip() or None,
    )
    db.add(submission)
    db.commit()
    return {"status": "received", "message": "Thanks -- a member of the CUSG team will review this before it appears."}


@router.get("/hearings/{hearing_id}/ics", response_class=PlainTextResponse)
def hearing_ics(hearing_id: str, db: Session = Depends(get_db)):
    """Section 5.1: "Add to calendar" (.ics export) per hearing.

    Real bug caught manually: this used to always emit an all-day
    VALUE=DATE event and never actually used the hearing's real start
    time (`time_str` was computed and then never referenced) -- every
    exported event showed up with no time at all, when the docket
    export almost always gives one. Now uses the same
    parse_hearing_time/parse_duration_minutes this app already relies
    on for the availability meter, converting the Mountain-time wall
    clock value to a real UTC instant (same ZoneInfo pattern as
    app/jobs/google_calendar_sync.py) -- falling back to the old
    all-day representation only when the time genuinely can't be
    parsed."""
    hearing = db.query(Hearing).filter(Hearing.id == hearing_id).first()
    if not hearing:
        raise HTTPException(404, "Hearing not found")

    dt = hearing.date.strftime("%Y%m%d")
    now_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    summary = f"{hearing.hearing_type_raw} - {hearing.case_number}"
    description = (
        f"{hearing.hearing_type_display}. Courtroom {hearing.courtroom or 'TBD'}. "
        f"Confirm on the official docket before attending -- times and locations can change."
    )
    location = f"{hearing.court_location.value} courtroom {hearing.courtroom or 'TBD'}"

    parsed_minutes = parse_hearing_time(hearing.time)
    if parsed_minutes is not None:
        start_local = datetime(
            hearing.date.year, hearing.date.month, hearing.date.day,
            parsed_minutes // 60, parsed_minutes % 60, tzinfo=MOUNTAIN_TZ,
        )
        start_utc = start_local.astimezone(timezone.utc)
        end_utc = start_utc + timedelta(minutes=parse_duration_minutes(hearing.duration))
        dt_lines = [
            f"DTSTART:{start_utc.strftime('%Y%m%dT%H%M%SZ')}",
            f"DTEND:{end_utc.strftime('%Y%m%dT%H%M%SZ')}",
        ]
    else:
        dt_lines = [f"DTSTART;VALUE=DATE:{dt}"]

    ics = "\n".join([
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//CUSG Boulder Court Tracker//EN",
        "BEGIN:VEVENT",
        f"UID:{hearing.id}@cusg-court-tracker",
        f"DTSTAMP:{now_stamp}",
        *dt_lines,
        f"SUMMARY:{summary}",
        f"DESCRIPTION:{description}",
        f"LOCATION:{location}",
        "END:VEVENT",
        "END:VCALENDAR",
    ])
    return PlainTextResponse(ics, media_type="text/calendar")


@router.get("/academic-calendar/current", response_model=Optional[AcademicCalendarPeriodOut])
def academic_calendar_current(db: Session = Depends(get_db)):
    return current_period(db)


@router.post("/subscriptions", response_model=SubscriptionOut)
def create_subscription(payload: SubscriptionCreate, request: Request, db: Session = Depends(get_db)):
    """Phase-4 doc, Section 2.2: rate-limited per IP like every other
    public write path -- nothing stopped someone from mass-creating
    subscription rows before this.

    Real bug caught manually (full-functionality pass): nothing stopped
    the exact same (email, filter_type, filter_value, frequency)
    combination from being inserted twice -- a double-click on the
    "Subscribe" button, or someone re-submitting because they weren't
    sure it worked the first time, silently created a permanent
    duplicate row. app/jobs/digest.py::run_weekly_digest sends one email
    per Subscription row with no dedup of its own, so that visitor would
    get the identical weekly digest twice, forever, with no way to
    notice or fix it themselves (each duplicate has its own unsubscribe
    token, and only one is ever shown). Now reuses the existing active
    subscription instead of inserting a second one -- the frontend
    (Subscribe.jsx) never reads `id`/`unsubscribe_token` back, so this is
    invisible to a real visitor either way. `personal_availability`'s
    `filter_value` is just a placeholder (see SubscriptionFilterType's
    docstring) -- its real content is `availability_cells`, so a
    resubmit there still updates the existing row's cells rather than
    silently keeping the stale ones."""
    if not check_rate_limit(f"subscribe:{client_ip(request)}", max_requests=10, window_seconds=600):
        raise HTTPException(429, "Too many requests -- try again in a few minutes.")

    sub = (
        db.query(Subscription)
        .filter(
            Subscription.email == payload.email,
            Subscription.filter_type == payload.filter_type,
            Subscription.filter_value == payload.filter_value,
            Subscription.frequency == payload.frequency,
            Subscription.is_active.is_(True),
        )
        .first()
    )
    if sub:
        if payload.availability_cells is not None:
            replace_owner_slots(db, AvailabilityOwnerType.personal_subscription, sub.id, payload.availability_cells)
            db.commit()
    else:
        sub = Subscription(
            email=payload.email,
            filter_type=payload.filter_type,
            filter_value=payload.filter_value,
            frequency=payload.frequency,
            unsubscribe_token=str(uuid.uuid4()),
        )
        db.add(sub)
        db.flush()  # assigns sub.id (default=_uuid) before we can attach AvailabilitySlot rows to it
        if payload.availability_cells:
            replace_owner_slots(db, AvailabilityOwnerType.personal_subscription, sub.id, payload.availability_cells)
        db.commit()
        db.refresh(sub)

    return SubscriptionOut(
        id=sub.id, email=sub.email, filter_type=sub.filter_type, filter_value=sub.filter_value,
        frequency=sub.frequency, unsubscribe_token=sub.unsubscribe_token,
        availability_cells=load_owner_cells(db, AvailabilityOwnerType.personal_subscription, sub.id),
    )


@router.delete("/subscriptions/{token}")
def unsubscribe(token: str, db: Session = Depends(get_db)):
    sub = db.query(Subscription).filter(Subscription.unsubscribe_token == token).first()
    if not sub:
        raise HTTPException(404, "Subscription not found")
    sub.is_active = False
    db.commit()
    return {"status": "unsubscribed"}


# --- Auto-update status + manual refresh (Phase-2 doc, Section 1) -----------

def _most_recent_docket_pull_attempt(db: Session) -> Optional[JobRun]:
    return (
        db.query(JobRun)
        .filter(JobRun.job_name == "docket_pull")
        .order_by(JobRun.started_at.desc())
        .first()
    )


@router.get("/data-status", response_model=DataStatusOut)
def data_status(db: Session = Depends(get_db)):
    """Powers the "Last updated HH:MM today" display and the refresh
    button's enabled/disabled state -- both computed from real JobRun rows
    (Section 8), not a new tracking table."""
    last_success = (
        db.query(JobRun)
        .filter(JobRun.job_name == "docket_pull", JobRun.success.is_(True))
        .order_by(JobRun.finished_at.desc())
        .first()
    )
    most_recent_attempt = _most_recent_docket_pull_attempt(db)
    next_refresh_available_at = None
    if most_recent_attempt:
        next_refresh_available_at = most_recent_attempt.started_at + timedelta(minutes=REFRESH_COOLDOWN_MINUTES)

    return DataStatusOut(
        last_updated_at=last_success.finished_at if last_success else None,
        next_refresh_available_at=next_refresh_available_at,
        refresh_cooldown_minutes=REFRESH_COOLDOWN_MINUTES,
    )


def _run_refresh_in_background() -> None:
    db = SessionLocal()
    try:
        run_docket_pull(db)
    except Exception:  # noqa: BLE001 - run_docket_pull already alerts + records the failed JobRun
        pass
    finally:
        db.close()


@router.post("/refresh", status_code=202)
def trigger_refresh(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Public, on-demand docket re-pull -- global cooldown, not per-user
    (one person's click updates data for everyone; there's one shared
    `last_updated_at`, not per-visitor state). Runs as a background task
    so the request returns immediately rather than holding the connection
    open for however long the live docket-export fetch takes; the
    frontend polls GET /data-status afterward to see the new timestamp.

    Also per-IP rate-limited (Section 6) -- mostly belt-and-suspenders on
    top of the global cooldown above, which already blocks *everyone*
    (not just one IP) once any refresh has run recently; the per-IP check
    additionally bounds how many failed/near-miss attempts one address can
    throw at this endpoint while the cooldown is active."""
    if not check_rate_limit(f"refresh:{client_ip(request)}", max_requests=5, window_seconds=600):
        raise HTTPException(429, "Too many refresh attempts from this address -- try again in a few minutes.")

    most_recent_attempt = _most_recent_docket_pull_attempt(db)
    now = datetime.utcnow()
    if most_recent_attempt:
        elapsed = now - most_recent_attempt.started_at
        cooldown = timedelta(minutes=REFRESH_COOLDOWN_MINUTES)
        if elapsed < cooldown:
            retry_at = most_recent_attempt.started_at + cooldown
            raise HTTPException(
                429,
                f"A refresh already ran recently. Try again after "
                f"{retry_at.isoformat(timespec='minutes')}Z.",
            )
    background_tasks.add_task(_run_refresh_in_background)
    return {"status": "refreshing"}

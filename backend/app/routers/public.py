"""
Public, unauthenticated endpoints (Section 5.1, 5.2, 5.3). Fully public
browsing, per Section 7: "none required to browse."
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.academic_calendar import current_period
from app.db import get_db
from app.models import (
    AppearanceType,
    CaseCategory,
    CommunitySubmission,
    CourtLocation,
    Hearing,
    HearingStatus,
    HearingTypeCategory,
    NewsMention,
    Subscription,
)
from app.schemas import (
    AcademicCalendarPeriodOut,
    CommunitySubmissionIn,
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

    return [HearingOut.from_orm_hearing(h) for h in filtered]


@router.get("/hearings/{hearing_id}", response_model=HearingOut)
def get_hearing(hearing_id: str, db: Session = Depends(get_db)):
    hearing = db.query(Hearing).filter(Hearing.id == hearing_id).first()
    if not hearing:
        raise HTTPException(404, "Hearing not found")
    return HearingOut.from_orm_hearing(hearing)


@router.post("/hearings/{hearing_id}/submissions", status_code=201)
def submit_community_details(hearing_id: str, payload: CommunitySubmissionIn, db: Session = Depends(get_db)):
    """Let a visitor add details (a case summary, a judge's name, etc.)
    they know about a hearing. Not published immediately -- goes to the
    admin review queue (Section 4's guardrails apply to visitor-submitted
    content just as much as to the automated pipelines; see
    docs/EXCLUSION_LOGIC.md). An Editor approving it is what actually
    updates the public-facing Hearing.judge_name or surfaces the summary."""
    hearing = db.query(Hearing).filter(Hearing.id == hearing_id).first()
    if not hearing:
        raise HTTPException(404, "Hearing not found")

    if payload.website:  # honeypot tripped -- pretend success, do nothing
        return {"status": "received"}

    if not (payload.summary_text or "").strip() and not (payload.judge_name or "").strip():
        raise HTTPException(400, "Provide a summary, a judge's name, or both")

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
    """Section 5.1: "Add to calendar" (.ics export) per hearing."""
    hearing = db.query(Hearing).filter(Hearing.id == hearing_id).first()
    if not hearing:
        raise HTTPException(404, "Hearing not found")

    dt = hearing.date.strftime("%Y%m%d")
    time_str = (hearing.time or "09:00").replace(" ", "").upper()
    ics = "\n".join([
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//CUSG Boulder Court Tracker//EN",
        "BEGIN:VEVENT",
        f"UID:{hearing.id}@cusg-court-tracker",
        f"DTSTAMP:{dt}T000000Z",
        f"DTSTART;VALUE=DATE:{dt}",
        f"SUMMARY:{hearing.hearing_type_display} - {hearing.case_number}",
        f"DESCRIPTION:{hearing.hearing_type_display}. Courtroom {hearing.courtroom or 'TBD'}. "
        f"Confirm on the official docket before attending -- times and locations can change.",
        f"LOCATION:{hearing.court_location.value} courtroom {hearing.courtroom or 'TBD'}",
        "END:VEVENT",
        "END:VCALENDAR",
    ])
    return PlainTextResponse(ics, media_type="text/calendar")


@router.get("/academic-calendar/current", response_model=Optional[AcademicCalendarPeriodOut])
def academic_calendar_current(db: Session = Depends(get_db)):
    return current_period(db)


@router.post("/subscriptions", response_model=SubscriptionOut)
def create_subscription(payload: SubscriptionCreate, db: Session = Depends(get_db)):
    sub = Subscription(
        email=payload.email,
        filter_type=payload.filter_type,
        filter_value=payload.filter_value,
        frequency=payload.frequency,
        unsubscribe_token=str(uuid.uuid4()),
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


@router.delete("/subscriptions/{token}")
def unsubscribe(token: str, db: Session = Depends(get_db)):
    sub = db.query(Subscription).filter(Subscription.unsubscribe_token == token).first()
    if not sub:
        raise HTTPException(404, "Subscription not found")
    sub.is_active = False
    db.commit()
    return {"status": "unsubscribed"}

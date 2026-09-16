"""
CUSG Supreme Court Justice features -- not in the original build prompt,
added on request once it became clear the tool's primary users are the
court's own 7 Justices, not just pre-law students generally:

1. Attendance: mark a Justice attending / not attending / maybe for a
   given hearing, visible to the rest of the court.
2. Recommendations: flag a hearing for the rest of the court with a
   required reason, landing both on a dedicated board (GET
   /recommendations) and as a callout directly on the hearing's own detail
   page, separate from the Editor-curated public blurb. Triggers an email
   to every Justice, plus anyone separately subscribed to
   new_recommendation (Section 5.3-style digest subscribers, a different
   audience -- see jobs/digest.py).

Both require a real Justice login (`require_justice`, checking
AdminUser.is_justice) -- this is a reversal from an earlier build-session
decision to make these fully open with no login at all. Re-gated on
explicit request once new features (an automatic email to every Justice,
and treating a recommendation as a real accountable action worth writing
to the Archive) raised the stakes of "anyone can act as anyone." Kept
separate from the Editor/Contributor curation role rather than folding
Justices into it (also an explicit choice): `require_justice` checks
`is_justice`, not `role == editor`, so a Justice-only account still can't
touch the curation tool in routers/admin.py, and vice versa.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_justice
from app.db import get_db
from app.jobs.digest import notify_all_justices_of_new_recommendation, notify_subscribers_of_new_recommendation
from app.models import (
    ActivityLogEntry,
    AdminUser,
    Hearing,
    HearingAttendance,
    HearingRecommendation,
)
from app.routers.account import _justice_out
from app.schemas import AttendanceIn, AttendanceOut, JusticeOut, RecommendationIn, RecommendationOut

router = APIRouter(prefix="/api", tags=["justices"])


@router.get("/justices", response_model=list[JusticeOut])
def list_justices(db: Session = Depends(get_db)):
    """Public: the full roster, so the UI can show all 7 names on a
    hearing (with "no response yet" for anyone who hasn't set a status)
    rather than only the ones who've already responded. Phase-3 doc,
    Section 3: this is also the "Meet the Justices" directory's data
    source -- same shape, now carrying full profile fields too."""
    justices = (
        db.query(AdminUser)
        .filter(AdminUser.is_justice.is_(True), AdminUser.is_active.is_(True))
        .all()
    )
    return [_justice_out(j) for j in justices]


@router.get("/justices/{justice_id}", response_model=JusticeOut)
def get_justice(justice_id: str, db: Session = Depends(get_db)):
    """Public: a single Justice's individual profile page (Section 3)."""
    justice = (
        db.query(AdminUser)
        .filter(AdminUser.id == justice_id, AdminUser.is_justice.is_(True), AdminUser.is_active.is_(True))
        .first()
    )
    if not justice:
        raise HTTPException(404, "Justice not found")
    return _justice_out(justice)


@router.put("/hearings/{hearing_id}/attendance", response_model=AttendanceOut)
def set_attendance(hearing_id: str, payload: AttendanceIn, db: Session = Depends(get_db),
                    justice: AdminUser = Depends(require_justice)):
    """Requires a real Justice login -- the identity is the authenticated
    user, not a `justice_id` picked from the roster (that was this
    endpoint's earlier, now-reversed, no-login design)."""
    hearing = db.query(Hearing).filter(Hearing.id == hearing_id).first()
    if not hearing:
        raise HTTPException(404, "Hearing not found")

    existing = (
        db.query(HearingAttendance)
        .filter(HearingAttendance.hearing_id == hearing_id, HearingAttendance.justice_id == justice.id)
        .first()
    )
    now = datetime.utcnow()
    if existing:
        existing.status = payload.status
        existing.note = payload.note
        existing.updated_at = now
        row = existing
    else:
        row = HearingAttendance(
            hearing_id=hearing_id, justice_id=justice.id,
            status=payload.status, note=payload.note, updated_at=now,
        )
        db.add(row)
    db.commit()

    return AttendanceOut(
        justice_id=justice.id, display_name=justice.display_name or justice.email,
        title=justice.title, status=row.status, note=row.note, updated_at=row.updated_at,
    )


@router.get("/recommendations", response_model=list[RecommendationOut])
def list_recommendations(hearing_id: Optional[str] = None, db: Session = Depends(get_db)):
    """Public read (no login) -- reading the board, and reading a specific
    hearing's recommendations for its own detail-page callout, stay open
    even though adding/removing one now requires a Justice login."""
    q = db.query(HearingRecommendation)
    if hearing_id:
        q = q.filter(HearingRecommendation.hearing_id == hearing_id)
    recs = q.order_by(HearingRecommendation.created_at.desc()).all()
    return [
        RecommendationOut(
            id=r.id, hearing_id=r.hearing_id, hearing_case_number=r.hearing.case_number,
            hearing_type_display=r.hearing.hearing_type_display, hearing_date=r.hearing.date,
            justice_id=r.justice_id,
            justice_display_name=r.justice.display_name or r.justice.email, justice_title=r.justice.title,
            note=r.note, created_at=r.created_at,
        )
        for r in recs
    ]


@router.post("/recommendations", response_model=RecommendationOut, status_code=201)
def create_recommendation(payload: RecommendationIn, db: Session = Depends(get_db),
                           justice: AdminUser = Depends(require_justice)):
    """Requires a real Justice login. Multiple Justices can each recommend
    the same hearing -- rows accumulate, none overwrite -- and every
    recommendation appears both on the board and as a callout on that
    hearing's own detail page (GET /recommendations?hearing_id=...)."""
    hearing = db.query(Hearing).filter(Hearing.id == payload.hearing_id).first()
    if not hearing:
        raise HTTPException(404, "Hearing not found")

    rec = HearingRecommendation(hearing_id=hearing.id, justice_id=justice.id, note=payload.note)
    db.add(rec)
    db.add(ActivityLogEntry(
        admin_user_email=justice.email, action="recommended_hearing",
        target_type="hearing", target_id=hearing.id,
        detail=f"{justice.display_name or justice.email} recommended {hearing.case_number}",
    ))
    db.commit()
    db.refresh(rec)
    # Two distinct audiences, both notified: every Justice automatically
    # (Section 4 of the phase-2 doc), plus anyone who separately
    # subscribed to new_recommendation on /subscribe (a public digest
    # feature, unrelated to being a Justice).
    notify_all_justices_of_new_recommendation(db, rec)
    notify_subscribers_of_new_recommendation(db, rec)

    return RecommendationOut(
        id=rec.id, hearing_id=hearing.id, hearing_case_number=hearing.case_number,
        hearing_type_display=hearing.hearing_type_display, hearing_date=hearing.date,
        justice_id=justice.id,
        justice_display_name=justice.display_name or justice.email, justice_title=justice.title,
        note=rec.note, created_at=rec.created_at,
    )


@router.delete("/recommendations/{recommendation_id}")
def delete_recommendation(recommendation_id: str, db: Session = Depends(get_db),
                           justice: AdminUser = Depends(require_justice)):
    """Any Justice can remove any recommendation (small, trusted roster of
    7), not just its author. Requires login now, unlike the earlier
    fully-open design."""
    rec = db.query(HearingRecommendation).filter(HearingRecommendation.id == recommendation_id).first()
    if not rec:
        raise HTTPException(404, "Recommendation not found")
    db.add(ActivityLogEntry(
        admin_user_email=justice.email, action="removed_recommendation",
        target_type="hearing", target_id=rec.hearing_id,
        detail=f"removed recommendation on {rec.hearing.case_number} originally by {rec.justice.display_name}",
    ))
    db.delete(rec)
    db.commit()
    return {"status": "removed"}

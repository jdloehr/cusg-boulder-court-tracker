"""
CUSG Supreme Court Justice features -- not in the original build prompt,
added on request once it became clear the tool's primary users are the
court's own 7 Justices, not just pre-law students generally:

1. Attendance: mark a Justice attending / not attending / maybe for a
   given hearing, visible to the rest of the court.
2. Recommendations: flag a hearing for the rest of the court with a note
   on why, landing on a dedicated board (GET /recommendations) separate
   from the Editor-curated public blurb.

Both are fully open, no login at all -- by request. The trust model (not
enforced server-side, a deliberate choice): the 7 real Justices are the
only realistic audience in practice, and are expected to only act as
themselves. See set_attendance()'s docstring for the full reasoning. This
is a different posture from the Editor/Contributor curation tool in
routers/admin.py, which stays role-gated (a separate, more consequential
system -- publishing public content, excluding hearings -- that this
change was not asked to touch).

The `/api/justices` roster (below) is what a client uses to know which
justice_id values are valid, since there's no login to derive one from.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    ActivityLogEntry,
    AdminUser,
    Hearing,
    HearingAttendance,
    HearingRecommendation,
)
from app.schemas import AttendanceIn, AttendanceOut, JusticeOut, RecommendationIn, RecommendationOut

router = APIRouter(prefix="/api", tags=["justices"])


@router.get("/justices", response_model=list[JusticeOut])
def list_justices(db: Session = Depends(get_db)):
    """Public: the full roster, so the UI can show all 7 names on a
    hearing (with "no response yet" for anyone who hasn't set a status)
    rather than only the ones who've already responded."""
    justices = (
        db.query(AdminUser)
        .filter(AdminUser.is_justice.is_(True), AdminUser.is_active.is_(True))
        .all()
    )
    return [JusticeOut(id=j.id, display_name=j.display_name or j.email, title=j.title) for j in justices]


@router.put("/hearings/{hearing_id}/attendance", response_model=AttendanceOut)
def set_attendance(hearing_id: str, payload: AttendanceIn, db: Session = Depends(get_db)):
    """No auth required, by request: the site has no separate login for
    regular visitors, and the 7 Justices are the only realistic audience
    for this in practice, so the trust model here is "anyone can reach
    this endpoint, on the expectation people only set their own status" --
    not enforced server-side, a deliberate simplicity-over-enforcement
    choice for a small trusted group rather than an oversight. `justice_id`
    comes from the request body (the public `/api/justices` roster) rather
    than a token, since there's no login to derive it from."""
    hearing = db.query(Hearing).filter(Hearing.id == hearing_id).first()
    if not hearing:
        raise HTTPException(404, "Hearing not found")

    justice = db.query(AdminUser).filter(
        AdminUser.id == payload.justice_id, AdminUser.is_justice.is_(True)
    ).first()
    if not justice:
        raise HTTPException(404, "Justice not found")

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
def list_recommendations(db: Session = Depends(get_db)):
    """Public read: "a special place for the rest of the justices to check
    out." Fully public: reading, adding, and removing a recommendation all
    require no login at all, by request -- see set_attendance()'s
    docstring for the trust model this and attendance share."""
    recs = db.query(HearingRecommendation).order_by(HearingRecommendation.created_at.desc()).all()
    return [
        RecommendationOut(
            id=r.id, hearing_id=r.hearing_id, hearing_case_number=r.hearing.case_number,
            hearing_type_display=r.hearing.hearing_type_display, hearing_date=r.hearing.date,
            justice_display_name=r.justice.display_name or r.justice.email, justice_title=r.justice.title,
            note=r.note, created_at=r.created_at,
        )
        for r in recs
    ]


@router.post("/recommendations", response_model=RecommendationOut, status_code=201)
def create_recommendation(payload: RecommendationIn, db: Session = Depends(get_db)):
    hearing = db.query(Hearing).filter(Hearing.id == payload.hearing_id).first()
    if not hearing:
        raise HTTPException(404, "Hearing not found")
    justice = db.query(AdminUser).filter(
        AdminUser.id == payload.justice_id, AdminUser.is_justice.is_(True)
    ).first()
    if not justice:
        raise HTTPException(404, "Justice not found")

    rec = HearingRecommendation(hearing_id=hearing.id, justice_id=justice.id, note=payload.note)
    db.add(rec)
    db.add(ActivityLogEntry(
        admin_user_email=justice.email, action="recommended_hearing",
        target_type="hearing", target_id=hearing.id,
        detail=f"{justice.display_name or justice.email} recommended {hearing.case_number}",
    ))
    db.commit()
    db.refresh(rec)

    return RecommendationOut(
        id=rec.id, hearing_id=hearing.id, hearing_case_number=hearing.case_number,
        hearing_type_display=hearing.hearing_type_display, hearing_date=hearing.date,
        justice_display_name=justice.display_name or justice.email, justice_title=justice.title,
        note=rec.note, created_at=rec.created_at,
    )


@router.delete("/recommendations/{recommendation_id}")
def delete_recommendation(recommendation_id: str, db: Session = Depends(get_db)):
    """No auth, same trust model as everything else in this file. There's
    no logged-in identity to attribute the removal to, so the activity log
    just records that it happened rather than claiming to know who did it."""
    rec = db.query(HearingRecommendation).filter(HearingRecommendation.id == recommendation_id).first()
    if not rec:
        raise HTTPException(404, "Recommendation not found")
    db.add(ActivityLogEntry(
        admin_user_email="(unauthenticated visitor)", action="removed_recommendation",
        target_type="hearing", target_id=rec.hearing_id,
        detail=f"removed recommendation on {rec.hearing.case_number} originally by {rec.justice.display_name}",
    ))
    db.delete(rec)
    db.commit()
    return {"status": "removed"}

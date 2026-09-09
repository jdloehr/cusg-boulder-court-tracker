"""
CUSG Supreme Court Justice features -- not in the original build prompt,
added on request once it became clear the tool's primary users are the
court's own 7 Justices, not just pre-law students generally:

1. Attendance: each Justice can mark themselves attending / not attending /
   maybe for a given hearing, visible to the rest of the court.
2. Recommendations: a Justice can flag a hearing for the rest of the court
   with a note on why, landing on a dedicated board (GET /recommendations)
   separate from the Editor-curated public blurb.

Reuses the same AdminUser/JWT auth as the curation team (see AdminUser's
docstring in app/models.py for why) -- `require_justice` just checks a
different flag than `require_editor`.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_justice
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
def set_attendance(hearing_id: str, payload: AttendanceIn, db: Session = Depends(get_db),
                    justice: AdminUser = Depends(require_justice)):
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
def list_recommendations(db: Session = Depends(get_db)):
    """Public read: "a special place for the rest of the justices to check
    out." Kept readable without login so a court intern or pre-law student
    looking at the site can see it too, matching Section 7's public-by-
    default posture -- only *adding*/*removing* a recommendation requires
    a Justice account."""
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
def create_recommendation(payload: RecommendationIn, db: Session = Depends(get_db),
                           justice: AdminUser = Depends(require_justice)):
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

    return RecommendationOut(
        id=rec.id, hearing_id=hearing.id, hearing_case_number=hearing.case_number,
        hearing_type_display=hearing.hearing_type_display, hearing_date=hearing.date,
        justice_display_name=justice.display_name or justice.email, justice_title=justice.title,
        note=rec.note, created_at=rec.created_at,
    )


@router.delete("/recommendations/{recommendation_id}")
def delete_recommendation(recommendation_id: str, db: Session = Depends(get_db),
                           justice: AdminUser = Depends(require_justice)):
    """Any Justice can remove a recommendation (small, trusted roster of
    7 -- see app/models.py::HearingRecommendation), not just its author.
    Logged either way so the court can see who removed what."""
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

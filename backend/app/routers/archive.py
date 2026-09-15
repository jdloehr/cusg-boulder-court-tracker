"""
Phase-2 doc, Section 5: Archive & Reflections -- a public, browsable
record of hearings actually attended and written up, separate from the
live/upcoming calendar (Section 5.1's list view).

Two submission paths converge on POST /archive, distinguished by whether
the caller is logged in as a Justice (get_optional_admin, not
require_justice -- this endpoint is public):
- Anyone (no login): "Submit a Summary" -- reflection_text required, a
  display name, no password. Publishes immediately, no approval queue
  (Section 5's own decision) -- Section 6's after-the-fact safeguards
  (submitter_ip logged internally, any Justice can edit/remove) cover what
  a pre-publish queue would otherwise catch.
- A logged-in Justice: "Mark Attendance" -- reflection_text is optional
  (recording "I was there" doesn't require a narrative), and the Justice
  is automatically added to `attendees`.

Both paths are restricted to hearings whose date has already passed
(Section 9 open question #4, resolved per the doc's own recommendation:
"to avoid marking attendance at something that hasn't happened yet").
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth import get_optional_admin, require_justice
from app.db import get_db
from app.rate_limit import check_rate_limit, client_ip
from app.moderation import is_likely_spam_or_profane
from app.models import AdminUser, ArchiveEntry, ArchiveSubmitterRole, CaseCategory, Hearing, ProceedingStage
from app.schemas import ArchiveEntryIn, ArchiveEntryOut, ArchiveEntryUpdateIn

router = APIRouter(prefix="/api/archive", tags=["archive"])


def _to_out(entry: ArchiveEntry) -> ArchiveEntryOut:
    return ArchiveEntryOut(
        id=entry.id,
        hearing_id=entry.hearing_id,
        hearing_case_number=entry.hearing.case_number,
        hearing_type_display=entry.hearing.hearing_type_display,
        hearing_date=entry.hearing.date,
        case_category=entry.hearing.case_category,
        proceeding_stage=entry.proceeding_stage,
        judge_name=entry.judge_name,
        attendees=json.loads(entry.attendees) if entry.attendees else [],
        reflection_text=entry.reflection_text,
        submitted_by_name=entry.submitted_by_name,
        submitted_by_role=entry.submitted_by_role,
        created_at=entry.created_at,
    )


@router.get("", response_model=list[ArchiveEntryOut])
def list_archive(
    db: Session = Depends(get_db),
    proceeding_stage: Optional[ProceedingStage] = None,
    case_category: Optional[CaseCategory] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
):
    """Public, no login. "Filterable by proceeding stage, case category,
    and date, shown reverse-chronologically -- a straightforward filtered
    list is enough" (Section 5)."""
    q = db.query(ArchiveEntry).join(Hearing, ArchiveEntry.hearing_id == Hearing.id)
    if proceeding_stage:
        q = q.filter(ArchiveEntry.proceeding_stage == proceeding_stage)
    if case_category:
        q = q.filter(Hearing.case_category == case_category)
    if date_from:
        q = q.filter(Hearing.date >= date_from)
    if date_to:
        q = q.filter(Hearing.date <= date_to)
    entries = q.order_by(ArchiveEntry.created_at.desc()).all()
    return [_to_out(e) for e in entries]


@router.get("/{entry_id}", response_model=ArchiveEntryOut)
def get_archive_entry(entry_id: str, db: Session = Depends(get_db)):
    entry = db.query(ArchiveEntry).filter(ArchiveEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(404, "Archive entry not found")
    return _to_out(entry)


@router.post("", response_model=ArchiveEntryOut, status_code=201)
def create_archive_entry(
    payload: ArchiveEntryIn,
    request: Request,
    db: Session = Depends(get_db),
    justice: Optional[AdminUser] = Depends(get_optional_admin),
):
    is_justice = bool(justice and justice.is_justice)
    ip = client_ip(request)
    # Section 6: rate-limit the public write path per IP -- a small,
    # trusted roster of Justices isn't the abuse surface this protects
    # against, so they're exempt.
    if not is_justice and not check_rate_limit(f"archive:{ip}", max_requests=5, window_seconds=600):
        raise HTTPException(429, "Too many submissions from this address -- try again in a few minutes.")

    if payload.website:  # honeypot tripped -- pretend success, do nothing real
        return ArchiveEntryOut(
            id="00000000-0000-0000-0000-000000000000", hearing_id=payload.hearing_id,
            hearing_case_number="", hearing_type_display="", hearing_date=date.today(),
            case_category=CaseCategory.other, proceeding_stage=payload.proceeding_stage,
            submitted_by_name=payload.submitted_by_name, submitted_by_role=ArchiveSubmitterRole.regular_user,
            created_at=datetime.utcnow(),
        )

    hearing = db.query(Hearing).filter(Hearing.id == payload.hearing_id).first()
    if not hearing:
        raise HTTPException(404, "Hearing not found")
    if hearing.date >= date.today():
        raise HTTPException(400, "Can't add an Archive entry for a hearing that hasn't happened yet")

    if not is_justice and not (payload.reflection_text or "").strip():
        raise HTTPException(400, "A reflection is required")

    for field, value in (("reflection_text", payload.reflection_text), ("judge_name", payload.judge_name)):
        if is_likely_spam_or_profane(value or ""):
            raise HTTPException(400, f"{field} looks like spam -- please rewrite it")

    attendees = [justice.display_name or justice.email] if is_justice else []

    entry = ArchiveEntry(
        hearing_id=hearing.id,
        proceeding_stage=payload.proceeding_stage,
        judge_name=payload.judge_name,
        attendees=json.dumps(attendees),
        reflection_text=payload.reflection_text,
        submitted_by_name=justice.display_name or justice.email if is_justice else payload.submitted_by_name,
        submitted_by_role=ArchiveSubmitterRole.justice if is_justice else ArchiveSubmitterRole.regular_user,
        submitter_ip=ip,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return _to_out(entry)


@router.patch("/{entry_id}", response_model=ArchiveEntryOut)
def update_archive_entry(entry_id: str, payload: ArchiveEntryUpdateIn, db: Session = Depends(get_db),
                          justice: AdminUser = Depends(require_justice)):
    """Any Justice can edit any entry (small, trusted roster) -- Section
    6's after-the-fact safeguard for a fully anonymous, unmoderated public
    input."""
    entry = db.query(ArchiveEntry).filter(ArchiveEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(404, "Archive entry not found")

    if payload.proceeding_stage is not None:
        entry.proceeding_stage = payload.proceeding_stage
    if payload.judge_name is not None:
        entry.judge_name = payload.judge_name
    if payload.reflection_text is not None:
        entry.reflection_text = payload.reflection_text
    if payload.attendees is not None:
        entry.attendees = json.dumps(payload.attendees)
    db.commit()
    db.refresh(entry)
    return _to_out(entry)


@router.delete("/{entry_id}")
def delete_archive_entry(entry_id: str, db: Session = Depends(get_db),
                          justice: AdminUser = Depends(require_justice)):
    entry = db.query(ArchiveEntry).filter(ArchiveEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(404, "Archive entry not found")
    db.delete(entry)
    db.commit()
    return {"status": "removed"}

"""
Phase-4 doc, Section 2.5: a "Report" link on every public Archive entry
and recommendation, since both publish with no pre-review (Section 5's
own decision, back in Phase 2). This is the after-the-fact safety net the
doc asks to strengthen now that the site is more visible -- doesn't
remove or hide anything itself, just notifies every Justice (Section
5.4's explicit choice over one designated moderator) and lands in the
dashboard's Reports queue for a Justice to act on with the tools that
already exist (edit/delete an Archive entry, delete a recommendation).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth import require_editor
from app.config import FRONTEND_URL
from app.db import get_db
from app.jobs.digest import notify_all_justices_of_report
from app.models import AdminUser, ArchiveEntry, ContentReport, HearingRecommendation, ReportTargetType
from app.rate_limit import check_rate_limit, client_ip
from app.schemas import ReportIn, ReportQueueOut

router = APIRouter(tags=["reports"])


def _target_exists_and_summary(db: Session, target_type: ReportTargetType, target_id: str) -> str:
    """Raises 404 if the reported content doesn't exist; otherwise
    returns a short human-readable summary for the queue view."""
    if target_type == ReportTargetType.archive_entry:
        entry = db.query(ArchiveEntry).filter(ArchiveEntry.id == target_id).first()
        if not entry:
            raise HTTPException(404, "That Archive entry no longer exists")
        return (entry.reflection_text or "(no reflection text)")[:200]
    rec = db.query(HearingRecommendation).filter(HearingRecommendation.id == target_id).first()
    if not rec:
        raise HTTPException(404, "That recommendation no longer exists")
    return (rec.note or "(no reason given)")[:200]


@router.post("/api/reports", status_code=201)
def create_report(payload: ReportIn, request: Request, db: Session = Depends(get_db)):
    """Public, no login -- reporting something shouldn't require an
    account. Rate-limited per IP like every other public write path
    (Phase-4 doc, Section 2.2)."""
    if not check_rate_limit(f"report:{client_ip(request)}", max_requests=10, window_seconds=600):
        raise HTTPException(429, "Too many reports from this address -- try again in a few minutes.")

    if payload.website:  # honeypot tripped -- pretend success, do nothing real
        return {"status": "received"}

    _target_exists_and_summary(db, payload.target_type, payload.target_id)  # 404s if missing

    report = ContentReport(
        target_type=payload.target_type, target_id=payload.target_id,
        reason=(payload.reason or "").strip() or None, reporter_ip=client_ip(request),
    )
    db.add(report)
    db.commit()

    admin_url = f"{FRONTEND_URL}/admin"
    notify_all_justices_of_report(db, payload.target_type.value, payload.target_id, report.reason, admin_url)
    return {"status": "received", "message": "Thanks -- every Justice has been notified."}


@router.get("/api/admin/reports", response_model=list[ReportQueueOut])
def list_reports(resolved: bool = False, db: Session = Depends(get_db),
                  admin: AdminUser = Depends(require_editor)):
    """Defaults to unresolved only (?resolved=true to see the resolved
    history) -- an Editor opening this tab wants the actionable queue
    first, same as every other review-queue endpoint in this app."""
    reports = (
        db.query(ContentReport)
        .filter(ContentReport.resolved.is_(resolved))
        .order_by(ContentReport.created_at.desc())
        .all()
    )
    out = []
    for r in reports:
        try:
            summary = _target_exists_and_summary(db, r.target_type, r.target_id)
            url = (
                f"/archive" if r.target_type == ReportTargetType.archive_entry
                else "/recommendations"
            )
        except HTTPException:
            summary, url = "(this content has since been removed)", None
        out.append(ReportQueueOut(
            id=r.id, target_type=r.target_type, target_id=r.target_id, reason=r.reason,
            resolved=r.resolved, created_at=r.created_at, target_summary=summary, target_url=url,
        ))
    return out


@router.post("/api/admin/reports/{report_id}/resolve")
def resolve_report(report_id: str, db: Session = Depends(get_db), admin: AdminUser = Depends(require_editor)):
    report = db.query(ContentReport).filter(ContentReport.id == report_id).first()
    if not report:
        raise HTTPException(404, "Report not found")
    report.resolved = True
    db.commit()
    return {"status": "resolved"}

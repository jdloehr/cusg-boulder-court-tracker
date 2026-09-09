"""
Role-gated admin/curation endpoints (Section 5.4). Two roles:
- editor: publish blurbs, manage the appellate supplement (federal +
  Colorado Supreme Court/Court of Appeals), exclude/flag hearings, set
  academic-calendar periods.
- contributor: draft blurbs, flag appellate candidates for review. Cannot
  publish or exclude.

Every mutating action writes an ActivityLogEntry so the small CUSG team can
coordinate without duplicating work (Section 5.4's "Activity log").
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import create_access_token, get_current_admin, require_editor, verify_password
from app.db import get_db
from app.jobs.appellate_supplement import PRESET_COURTS, search_candidates
from app.models import (
    AcademicCalendarPeriod,
    ActivityLogEntry,
    AdminUser,
    AppearanceType,
    CaseCategory,
    CommunitySubmission,
    CourtLocation,
    Hearing,
    HearingSource,
    HearingStatus,
    HearingTypeCategory,
    MatchStatus,
    NewsMention,
    SubmissionStatus,
)
from app.schemas import (
    AcademicCalendarPeriodIn,
    AcademicCalendarPeriodOut,
    AdminLoginRequest,
    AdminLoginResponse,
    AppellateCandidateOut,
    BlurbDraftIn,
    CommunitySubmissionReviewOut,
    ExclusionIn,
    HearingOut,
    NewsMentionOut,
    PublishAppellateCandidateIn,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _log(db: Session, admin: AdminUser, action: str, target_type: str,
         target_id: Optional[str] = None, detail: Optional[str] = None) -> None:
    db.add(ActivityLogEntry(admin_user_email=admin.email, action=action,
                             target_type=target_type, target_id=target_id, detail=detail))


@router.post("/login", response_model=AdminLoginResponse)
def login(payload: AdminLoginRequest, db: Session = Depends(get_db)):
    """Single login for both curation-team accounts (Editor/Contributor)
    and CUSG Justice accounts -- see AdminUser's docstring in
    app/models.py. The frontend routes to the curation dashboard or the
    justice-facing views based on the role/is_justice fields returned
    here."""
    user = db.query(AdminUser).filter(AdminUser.email == payload.email).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(401, "Invalid credentials")
    return AdminLoginResponse(
        access_token=create_access_token(user),
        role=user.role.value if user.role else None,
        is_justice=user.is_justice,
        display_name=user.display_name,
        title=user.title,
    )


# --- Review queues -----------------------------------------------------------

@router.get("/review-queue/hearings", response_model=list[HearingOut])
def review_queue_hearings(db: Session = Depends(get_db), admin: AdminUser = Depends(get_current_admin)):
    """Hearings the automated pipeline couldn't confidently categorize:
    case_category == other (case-number prefix didn't match the decode
    table) or hearing_type_category == unrecognized (schema drift, Section
    8)."""
    hearings = (
        db.query(Hearing)
        .filter(
            (Hearing.case_category == CaseCategory.other)
            | (Hearing.hearing_type_category == HearingTypeCategory.unrecognized)
        )
        .order_by(Hearing.date)
        .all()
    )
    return [HearingOut.from_orm_hearing(h) for h in hearings]


@router.get("/review-queue/news-mentions", response_model=list[NewsMentionOut])
def review_queue_news_mentions(db: Session = Depends(get_db), admin: AdminUser = Depends(get_current_admin)):
    return (
        db.query(NewsMention)
        .filter(NewsMention.match_status == MatchStatus.unmatched_review)
        .order_by(NewsMention.fetched_at.desc())
        .all()
    )


@router.post("/news-mentions/{mention_id}/link")
def link_news_mention(mention_id: str, hearing_id: str, db: Session = Depends(get_db),
                       admin: AdminUser = Depends(get_current_admin)):
    mention = db.query(NewsMention).filter(NewsMention.id == mention_id).first()
    if not mention:
        raise HTTPException(404, "News mention not found")
    hearing = db.query(Hearing).filter(Hearing.id == hearing_id).first()
    if not hearing:
        raise HTTPException(404, "Hearing not found")
    mention.hearing_id = hearing.id
    mention.match_status = MatchStatus.manually_linked
    _log(db, admin, "manually_linked_news_mention", "news_mention", mention.id,
         f"linked to hearing {hearing.case_number}")
    db.commit()
    return {"status": "linked"}


@router.delete("/news-mentions/{mention_id}")
def discard_news_mention(mention_id: str, db: Session = Depends(get_db),
                          admin: AdminUser = Depends(get_current_admin)):
    mention = db.query(NewsMention).filter(NewsMention.id == mention_id).first()
    if not mention:
        raise HTTPException(404, "News mention not found")
    _log(db, admin, "discarded_news_mention", "news_mention", mention.id, mention.headline)
    db.delete(mention)
    db.commit()
    return {"status": "discarded"}


# --- Community submissions ("add details" from a public visitor) ------------

@router.get("/review-queue/community-submissions", response_model=list[CommunitySubmissionReviewOut])
def review_queue_community_submissions(db: Session = Depends(get_db), admin: AdminUser = Depends(get_current_admin)):
    pending = (
        db.query(CommunitySubmission)
        .filter(CommunitySubmission.status == SubmissionStatus.pending)
        .order_by(CommunitySubmission.submitted_at)
        .all()
    )
    return [
        CommunitySubmissionReviewOut(
            id=s.id, summary_text=s.summary_text, judge_name=s.judge_name, status=s.status,
            submitted_at=s.submitted_at, submitter_context=s.submitter_context,
            hearing_id=s.hearing_id, hearing_case_number=s.hearing.case_number,
        )
        for s in pending
    ]


@router.post("/community-submissions/{submission_id}/approve")
def approve_community_submission(submission_id: str, db: Session = Depends(get_db),
                                  admin: AdminUser = Depends(require_editor)):
    """Editor-only: Section 4's judgment-call guardrails apply to visitor
    submissions the same way they apply to the automated pipelines, so this
    follows the same publish authority as blurbs/exclusion, not the lighter
    draft-blurb bar. Approving copies judge_name onto the Hearing (last
    approval wins) and marks the submission approved so its summary_text
    becomes publicly visible (see HearingOut.community_submissions)."""
    submission = db.query(CommunitySubmission).filter(CommunitySubmission.id == submission_id).first()
    if not submission:
        raise HTTPException(404, "Submission not found")
    submission.status = SubmissionStatus.approved
    submission.reviewed_by = admin.email
    submission.reviewed_at = datetime.utcnow()
    if submission.judge_name:
        submission.hearing.judge_name = submission.judge_name
    _log(db, admin, "approved_community_submission", "community_submission", submission.id,
         f"hearing {submission.hearing.case_number}")
    db.commit()
    return {"status": "approved"}


@router.post("/community-submissions/{submission_id}/reject")
def reject_community_submission(submission_id: str, db: Session = Depends(get_db),
                                 admin: AdminUser = Depends(require_editor)):
    submission = db.query(CommunitySubmission).filter(CommunitySubmission.id == submission_id).first()
    if not submission:
        raise HTTPException(404, "Submission not found")
    submission.status = SubmissionStatus.rejected
    submission.reviewed_by = admin.email
    submission.reviewed_at = datetime.utcnow()
    _log(db, admin, "rejected_community_submission", "community_submission", submission.id,
         f"hearing {submission.hearing.case_number}")
    db.commit()
    return {"status": "rejected"}


# --- Blurbs & exclusion -------------------------------------------------------

@router.patch("/hearings/{hearing_id}/draft-blurb")
def draft_blurb(hearing_id: str, payload: BlurbDraftIn, db: Session = Depends(get_db),
                 admin: AdminUser = Depends(get_current_admin)):
    """Editor or Contributor: draft a blurb. Not publicly visible until an
    Editor calls publish-blurb below."""
    hearing = db.query(Hearing).filter(Hearing.id == hearing_id).first()
    if not hearing:
        raise HTTPException(404, "Hearing not found")
    hearing.curated_blurb_draft = payload.curated_blurb_draft
    _log(db, admin, "drafted_blurb", "hearing", hearing.id)
    db.commit()
    return {"status": "draft saved"}


@router.post("/hearings/{hearing_id}/publish-blurb")
def publish_blurb(hearing_id: str, db: Session = Depends(get_db),
                   admin: AdminUser = Depends(require_editor)):
    hearing = db.query(Hearing).filter(Hearing.id == hearing_id).first()
    if not hearing:
        raise HTTPException(404, "Hearing not found")
    if not hearing.curated_blurb_draft:
        raise HTTPException(400, "No draft blurb to publish")
    hearing.curated_blurb = hearing.curated_blurb_draft
    _log(db, admin, "published_blurb", "hearing", hearing.id)
    db.commit()
    return {"status": "published"}


@router.patch("/hearings/{hearing_id}/exclusion")
def set_exclusion(hearing_id: str, payload: ExclusionIn, db: Session = Depends(get_db),
                   admin: AdminUser = Depends(require_editor)):
    """Section 4/5.4: Editor judgment call on DR / other borderline-sensitive
    hearings. Juvenile hearings are already excluded by the pipeline itself
    (app/jobs/docket_pull.py) and don't need this endpoint."""
    hearing = db.query(Hearing).filter(Hearing.id == hearing_id).first()
    if not hearing:
        raise HTTPException(404, "Hearing not found")
    hearing.is_excluded = payload.is_excluded
    hearing.exclusion_reason = payload.exclusion_reason
    _log(db, admin, "set_exclusion", "hearing", hearing.id,
         f"is_excluded={payload.is_excluded} reason={payload.exclusion_reason}")
    db.commit()
    return {"status": "updated"}


# --- Appellate supplement (Section 2.3 / 5.4, expanded to CO Supreme Court/Court of Appeals) --

@router.get("/appellate-candidates/search", response_model=list[AppellateCandidateOut])
def appellate_candidate_search(query: str, court: Optional[str] = None, result_type: str = "o",
                                admin: AdminUser = Depends(get_current_admin)):
    candidates = search_candidates(query, court=court, result_type=result_type)
    return [AppellateCandidateOut(**vars(c)) for c in candidates]


@router.get("/appellate-candidates/courts")
def appellate_candidate_court_presets(admin: AdminUser = Depends(get_current_admin)):
    """Quick-pick court options for the search form -- see PRESET_COURTS in
    app/jobs/appellate_supplement.py."""
    return PRESET_COURTS


@router.post("/appellate-candidates/flag")
def flag_appellate_candidate(candidate: AppellateCandidateOut, db: Session = Depends(get_db),
                              admin: AdminUser = Depends(get_current_admin)):
    """Contributor (or Editor) flags a CourtListener result as worth an
    Editor reviewing for the public feed. Logged to the activity log rather
    than a dedicated table -- see docs/ARCHITECTURE.md."""
    _log(db, admin, "flagged_appellate_candidate", "appellate_candidate", None,
         json.dumps(candidate.model_dump()))
    db.commit()
    return {"status": "flagged for review"}


@router.get("/appellate-candidates/flagged")
def list_flagged_appellate_candidates(db: Session = Depends(get_db), admin: AdminUser = Depends(get_current_admin)):
    entries = (
        db.query(ActivityLogEntry)
        .filter(ActivityLogEntry.action == "flagged_appellate_candidate")
        .order_by(ActivityLogEntry.created_at.desc())
        .all()
    )
    return [{"flagged_by": e.admin_user_email, "at": e.created_at, "candidate": json.loads(e.detail)}
            for e in entries]


@router.post("/appellate-candidates/publish", response_model=HearingOut)
def publish_appellate_candidate(payload: PublishAppellateCandidateIn, db: Session = Depends(get_db),
                                 admin: AdminUser = Depends(require_editor)):
    """Editor manually curates a CourtListener candidate (federal, or
    Colorado Supreme Court/Court of Appeals) into the public feed as a
    source=federal_courtlistener Hearing row. Deliberately manual (Section
    2.3: "a team member flags this ... case is Boulder-relevant rather
    than a keyword filter alone") -- see app/jobs/appellate_supplement.py's
    module docstring for why this is still curator-driven even for
    Colorado's own appellate courts."""
    from app.hearing_types import classify_hearing_type

    type_result = classify_hearing_type(payload.hearing_type_raw)
    hearing = Hearing(
        source=HearingSource.federal_courtlistener,
        case_number=payload.docket_number,
        case_category=CaseCategory.civil,
        party_names=json.dumps([payload.case_name]),
        hearing_type_raw=payload.hearing_type_raw,
        hearing_type_display=type_result.display,
        hearing_type_category=type_result.category.value,
        date=payload.date,
        time=payload.time,
        court_location=payload.court_location,
        courtroom=payload.court_note,
        appearance_type=AppearanceType.in_person,
        curated_blurb=payload.curated_blurb,
        status=HearingStatus.scheduled,
    )
    db.add(hearing)
    _log(db, admin, "published_appellate_candidate", "hearing", None, payload.case_name)
    db.commit()
    db.refresh(hearing)
    return HearingOut.from_orm_hearing(hearing)


# --- Academic calendar (Section 5.4 / 5.5) -----------------------------------

@router.get("/academic-calendar", response_model=list[AcademicCalendarPeriodOut])
def list_academic_calendar(db: Session = Depends(get_db), admin: AdminUser = Depends(get_current_admin)):
    return db.query(AcademicCalendarPeriod).order_by(AcademicCalendarPeriod.start_date).all()


@router.post("/academic-calendar", response_model=AcademicCalendarPeriodOut)
def create_academic_calendar_period(payload: AcademicCalendarPeriodIn, db: Session = Depends(get_db),
                                     admin: AdminUser = Depends(require_editor)):
    period = AcademicCalendarPeriod(**payload.model_dump())
    db.add(period)
    _log(db, admin, "created_academic_calendar_period", "academic_calendar_period", None, payload.label)
    db.commit()
    db.refresh(period)
    return period


# --- Activity log --------------------------------------------------------------

@router.get("/activity-log")
def activity_log(db: Session = Depends(get_db), admin: AdminUser = Depends(get_current_admin)):
    entries = db.query(ActivityLogEntry).order_by(ActivityLogEntry.created_at.desc()).limit(200).all()
    return [
        {"at": e.created_at, "admin": e.admin_user_email, "action": e.action,
         "target_type": e.target_type, "target_id": e.target_id, "detail": e.detail}
        for e in entries
    ]

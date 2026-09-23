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
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth import create_access_token, get_current_admin, require_editor, verify_password
from app.db import get_db
from app.jobs.appellate_supplement import PRESET_COURTS, search_candidates
from app.jobs.news_monitor import backfill_rematch_all
from app.rate_limit import check_rate_limit, client_ip
from app.totp import consume_backup_code, verify_totp_code
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
    LivestreamSourceType,
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
    LinkNewsMentionIn,
    NewsMentionOut,
    PublishAppellateCandidateIn,
    SuggestedHearingOut,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _log(db: Session, admin: AdminUser, action: str, target_type: str,
         target_id: Optional[str] = None, detail: Optional[str] = None) -> None:
    db.add(ActivityLogEntry(admin_user_email=admin.email, action=action,
                             target_type=target_type, target_id=target_id, detail=detail))


# Phase-4 doc, Section 2.3: account lockout, layered on top of the
# existing per-IP rate limit below (that one stops one address hammering
# any account; this one stops a distributed attempt -- many IPs -- aimed
# at one specific account).
LOCKOUT_THRESHOLD = 10
LOCKOUT_MINUTES = 15


@router.post("/login", response_model=AdminLoginResponse)
def login(payload: AdminLoginRequest, request: Request, db: Session = Depends(get_db)):
    """Single login for both curation-team accounts (Editor/Contributor)
    and CUSG Justice accounts -- see AdminUser's docstring in
    app/models.py. The frontend routes to the curation dashboard or the
    justice-facing views based on the role/is_justice fields returned
    here.

    Phase-3 doc, Section 5: rate-limited per IP (not per email -- the
    roster is only 7-8 people, so a per-IP budget is enough to stop
    brute-forcing any one of those accounts without needing to track a
    separate counter per email address).

    Phase-4 doc, Section 2.3 adds: account lockout after repeated failed
    attempts (regardless of IP), and a second factor for accounts that
    have TOTP enabled -- a 428 response (not 401) signals "right password,
    now send a code" so the frontend can prompt for one without treating
    it as a failed login."""
    if not check_rate_limit(f"login:{client_ip(request)}", max_requests=10, window_seconds=600):
        raise HTTPException(429, "Too many login attempts from this address -- try again in a few minutes.")

    user = db.query(AdminUser).filter(AdminUser.email == payload.email).first()
    now = datetime.utcnow()

    if user and user.locked_until and user.locked_until > now:
        retry_at = user.locked_until.isoformat(timespec="minutes")
        raise HTTPException(
            423, f"Account temporarily locked after repeated failed attempts. Try again after {retry_at}Z."
        )

    def _register_failure() -> None:
        if not user:
            return
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= LOCKOUT_THRESHOLD:
            user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
            user.failed_login_attempts = 0
        db.commit()

    if not user or not verify_password(payload.password, user.hashed_password):
        _register_failure()
        raise HTTPException(401, "Invalid credentials")

    if user.totp_enabled:
        if not payload.totp_code:
            raise HTTPException(428, "2FA code required")
        if not verify_totp_code(user.totp_secret, payload.totp_code):
            remaining = consume_backup_code(
                json.loads(user.totp_backup_code_hashes) if user.totp_backup_code_hashes else [],
                payload.totp_code,
            )
            if remaining is None:
                _register_failure()
                raise HTTPException(401, "Invalid 2FA code")
            user.totp_backup_code_hashes = json.dumps(remaining)

    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()

    return AdminLoginResponse(
        access_token=create_access_token(user),
        id=user.id,
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


def _news_mention_out(m: NewsMention) -> NewsMentionOut:
    suggested = None
    if m.match_status == MatchStatus.suggested_pending_review and m.hearing:
        h = m.hearing
        suggested = SuggestedHearingOut(
            id=h.id, case_number=h.case_number, hearing_type_display=h.hearing_type_display,
            date=h.date, party_names=h.party_names,
        )
    return NewsMentionOut(
        id=m.id, article_url=m.article_url, source_name=m.source_name, headline=m.headline,
        published_at=m.published_at, match_status=m.match_status, match_confidence=m.match_confidence,
        extracted_case_numbers=m.extracted_case_numbers, extracted_party_candidates=m.extracted_party_candidates,
        match_signals=m.match_signals, suggested_hearing=suggested,
    )


# Phase-6 doc, Section 4: "make the review queue actually usable." The
# queue now covers two real states -- a medium-confidence *suggested*
# match with a candidate hearing ready to confirm/reject in one click,
# and the original no-candidate-at-all unmatched_review -- shown together
# so a curator sees everything actually waiting for a decision in one
# place, suggested items first since those take one click to resolve.
@router.get("/review-queue/news-mentions", response_model=list[NewsMentionOut])
def review_queue_news_mentions(db: Session = Depends(get_db), admin: AdminUser = Depends(get_current_admin)):
    mentions = (
        db.query(NewsMention)
        .filter(NewsMention.match_status.in_([MatchStatus.suggested_pending_review, MatchStatus.unmatched_review]))
        .order_by(NewsMention.fetched_at.desc())
        .all()
    )
    # Suggested-with-a-ready-candidate first (one click to resolve),
    # then the general unmatched queue -- sorted in Python rather than
    # via the enum column's DB-level ordering, which isn't portable
    # (Postgres native enums sort by declaration order; SQLite's
    # string-backed column sorts alphabetically -- neither reliably
    # matches the priority intended here).
    mentions.sort(key=lambda m: 0 if m.match_status == MatchStatus.suggested_pending_review else 1)
    return [_news_mention_out(m) for m in mentions]


@router.get("/review-queue/news-mentions/count")
def review_queue_news_mentions_count(db: Session = Depends(get_db), admin: AdminUser = Depends(get_current_admin)):
    """A visible count, not just a list you have to open to notice --
    Section 4's own complaint about the original queue: "it isn't easy
    to forget about" only holds if the count is surfaced somewhere
    without having to click into the tab first."""
    count = (
        db.query(NewsMention)
        .filter(NewsMention.match_status.in_([MatchStatus.suggested_pending_review, MatchStatus.unmatched_review]))
        .count()
    )
    return {"count": count}


@router.post("/news-mentions/{mention_id}/confirm", response_model=NewsMentionOut)
def confirm_suggested_news_mention(mention_id: str, db: Session = Depends(get_db),
                                    admin: AdminUser = Depends(get_current_admin)):
    """One-click confirm for a suggested_pending_review mention -- the
    candidate hearing (already attached as hearing_id) becomes the real
    link; no re-selecting anything."""
    mention = db.query(NewsMention).filter(NewsMention.id == mention_id).first()
    if not mention:
        raise HTTPException(404, "News mention not found")
    if mention.match_status != MatchStatus.suggested_pending_review or not mention.hearing_id:
        raise HTTPException(400, "This mention has no suggested match to confirm")
    mention.match_status = MatchStatus.manually_linked
    _log(db, admin, "confirmed_suggested_news_mention", "news_mention", mention.id,
         f"confirmed suggested link to hearing {mention.hearing.case_number}")
    db.commit()
    db.refresh(mention)
    return _news_mention_out(mention)


@router.post("/news-mentions/{mention_id}/reject", response_model=NewsMentionOut)
def reject_suggested_news_mention(mention_id: str, db: Session = Depends(get_db),
                                   admin: AdminUser = Depends(get_current_admin)):
    """One-click reject for a suggested_pending_review mention -- the
    algorithm's candidate was wrong; demotes to the general unmatched
    queue (not discarded outright -- a human just said "not this one,"
    not "not court-relevant") so it's still findable for a manual link."""
    mention = db.query(NewsMention).filter(NewsMention.id == mention_id).first()
    if not mention:
        raise HTTPException(404, "News mention not found")
    if mention.match_status != MatchStatus.suggested_pending_review:
        raise HTTPException(400, "This mention has no suggested match to reject")
    rejected_hearing = mention.hearing.case_number if mention.hearing else None
    mention.hearing_id = None
    mention.match_status = MatchStatus.unmatched_review
    _log(db, admin, "rejected_suggested_news_mention", "news_mention", mention.id,
         f"rejected suggested link to hearing {rejected_hearing}")
    db.commit()
    db.refresh(mention)
    return _news_mention_out(mention)


@router.post("/news-mentions/{mention_id}/link", response_model=NewsMentionOut)
def link_news_mention(mention_id: str, payload: LinkNewsMentionIn, db: Session = Depends(get_db),
                       admin: AdminUser = Depends(get_current_admin)):
    """Phase-6 doc, Section 4: link by case number directly (the
    algorithm genuinely couldn't figure this one out on its own), or by
    hearing_id if a curator already has it -- exactly one of the two."""
    mention = db.query(NewsMention).filter(NewsMention.id == mention_id).first()
    if not mention:
        raise HTTPException(404, "News mention not found")

    if bool(payload.hearing_id) == bool(payload.case_number):
        raise HTTPException(400, "Provide exactly one of hearing_id or case_number")

    if payload.case_number:
        hearing = db.query(Hearing).filter(Hearing.case_number.ilike(payload.case_number)).first()
        if not hearing:
            raise HTTPException(404, f"No hearing found with case number {payload.case_number!r}")
    else:
        hearing = db.query(Hearing).filter(Hearing.id == payload.hearing_id).first()
        if not hearing:
            raise HTTPException(404, "Hearing not found")

    mention.hearing_id = hearing.id
    mention.match_status = MatchStatus.manually_linked
    _log(db, admin, "manually_linked_news_mention", "news_mention", mention.id,
         f"linked to hearing {hearing.case_number}")
    db.commit()
    db.refresh(mention)
    return _news_mention_out(mention)


@router.post("/news-mentions/backfill-rematch")
def backfill_rematch_news_mentions(db: Session = Depends(get_db), admin: AdminUser = Depends(require_editor)):
    """Explicit, on-demand: re-evaluates every unresolved (unmatched/
    suggested) NewsMention under the *current* matching logic -- for
    when that logic has changed since some of the backlog was first
    ingested (see app/jobs/news_monitor.py::backfill_rematch_all's
    docstring for the real situation this shipped to fix: 487 rows
    evaluated under pre-confidence-tiering logic, almost all genuine
    noise the new relevance gate now correctly discards). Editor-only --
    unlike confirm/reject/link, this can reclassify a large chunk of the
    queue in bulk, worth gating a notch more than the routine actions."""
    summary = backfill_rematch_all(db, datetime.utcnow())
    _log(db, admin, "backfilled_news_mention_rematch", "news_mention", None, json.dumps(summary))
    db.commit()
    return summary


@router.delete("/news-mentions/{mention_id}")
def discard_news_mention(mention_id: str, db: Session = Depends(get_db),
                          admin: AdminUser = Depends(get_current_admin)):
    """A curator's own explicit "remove this from the queue entirely"
    action -- deletes the row outright. Distinct from
    MatchStatus.discarded (app/models.py), which the pipeline itself sets
    automatically for zero-signal articles and which *keeps* the row
    (so the same URL isn't re-fetched and re-evaluated forever)."""
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
    from app.livestream import default_livestream

    type_result = classify_hearing_type(payload.hearing_type_raw)
    livestream_type, livestream_url = default_livestream(payload.court_location)
    if payload.federal_audio_line_url:
        livestream_type, livestream_url = LivestreamSourceType.federal_audio_line, payload.federal_audio_line_url
    hearing = Hearing(
        source=HearingSource.federal_courtlistener,
        case_number=payload.docket_number,
        case_category=payload.case_category,
        party_names=json.dumps([payload.case_name]),
        hearing_type_raw=payload.hearing_type_raw,
        hearing_type_display=type_result.display,
        hearing_type_category=type_result.category.value,
        date=payload.date,
        time=payload.time,
        court_location=payload.court_location,
        courtroom=payload.court_note,
        livestream_source_type=livestream_type,
        livestream_url=livestream_url,
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

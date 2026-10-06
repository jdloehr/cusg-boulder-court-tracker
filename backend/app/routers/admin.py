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

from app.auth import create_access_token, get_current_admin, hash_password, require_editor, verify_password
from app.db import get_db
from app.jobs.appellate_supplement import PRESET_COURTS, search_candidates
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
    NewsMentionHearingSummaryOut,
    NewsMentionOut,
    PublishAppellateCandidateIn,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _log(db: Session, admin: AdminUser, action: str, target_type: str,
         target_id: Optional[str] = None, detail: Optional[str] = None) -> None:
    db.add(ActivityLogEntry(admin_user_email=admin.email, action=action,
                             target_type=target_type, target_id=target_id, detail=detail))


# Oct 2026 review item 4: the original Phase-4 doc, Section 2.3 design
# was a flat 10-failure / 15-minute lockout with a distinct 423
# response. Both turned out to be real problems, found in the Oct 2026
# review:
# - A flat lockout is itself a denial-of-service lever -- anyone who
#   knows (or guesses) an account's email can lock it out for 15
#   minutes at a time indefinitely, including the real owner, just by
#   sending 10 wrong passwords. Nothing about it requires guessing
#   correctly or even being the same IP twice (this stacks with, not
#   instead of, the per-IP rate limit below).
# - The 423 response -- and the plain fact that *something* distinct
#   happens after enough failed attempts -- leaks whether an email has
#   an account at all, before a single correct credential is ever
#   checked.
# Replaced with per-account exponential backoff (a correct password is
# *never* refused outright, it just becomes progressively slower to
# retry a wrong one) and a response that's indistinguishable from a
# plain wrong password either way. Reuses the existing
# failed_login_attempts/locked_until columns -- same fields, new
# semantics (locked_until is now "next allowed attempt," not "locked
# until a flat timer expires") -- rather than adding new ones.
LOGIN_BACKOFF_GRACE_ATTEMPTS = 2  # the first couple of typos cost nothing
LOGIN_BACKOFF_MAX_SECONDS = 300  # capped at 5 minutes, per the review


def _login_backoff_seconds(attempts: int) -> int:
    if attempts <= LOGIN_BACKOFF_GRACE_ATTEMPTS:
        return 0
    return min(2 ** (attempts - LOGIN_BACKOFF_GRACE_ATTEMPTS), LOGIN_BACKOFF_MAX_SECONDS)


# A real, validly-formatted bcrypt hash of a string nobody will ever
# actually submit -- checked (and always fails) when the email doesn't
# match any account, so that request costs roughly the same time as one
# for a real email with a wrong password. Skipping bcrypt entirely for
# an unknown email would be a timing side-channel revealing which
# emails have accounts -- computed once at import time, not per
# request, since bcrypt's own deliberate slowness is the whole point
# and re-hashing it per request would just add needless load.
_DUMMY_PASSWORD_HASH = hash_password("not-a-real-password-this-is-only-for-timing")


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

    Phase-4 doc, Section 2.3 / Oct 2026 review: a second factor for
    accounts that have TOTP enabled -- a 428 response (not 401) signals
    "right password, now send a code" so the frontend can prompt for one
    without treating it as a failed login (this one's fine to keep
    distinct: reaching it already proves the caller knows the real
    password, so it's not an enumeration leak the way the old 423 was).
    Backoff and credential-enumeration protections are per
    _login_backoff_seconds/_DUMMY_PASSWORD_HASH above."""
    if not check_rate_limit(f"login:{client_ip(request)}", max_requests=10, window_seconds=600):
        raise HTTPException(429, "Too many login attempts from this address -- try again in a few minutes.")

    user = db.query(AdminUser).filter(AdminUser.email == payload.email).first()
    now = datetime.utcnow()

    if user is None:
        verify_password(payload.password, _DUMMY_PASSWORD_HASH)  # timing-equalizing dummy check
        raise HTTPException(401, "Invalid credentials")

    if user.locked_until and user.locked_until > now:
        # Same response as a wrong password -- indistinguishable from
        # one, so this can't be used to probe which accounts exist or
        # have had recent failed attempts.
        raise HTTPException(401, "Invalid credentials")

    def _register_failure() -> None:
        user.failed_login_attempts += 1
        delay = _login_backoff_seconds(user.failed_login_attempts)
        user.locked_until = now + timedelta(seconds=delay) if delay else None
        db.commit()

    if not verify_password(payload.password, user.hashed_password):
        _register_failure()
        raise HTTPException(401, "Invalid credentials")

    if user.totp_enabled:
        if not payload.totp_code:
            raise HTTPException(428, "2FA code required")
        accepted, step = verify_totp_code(user.totp_secret, payload.totp_code, user.last_totp_step)
        if accepted:
            user.last_totp_step = step  # Oct 2026 review item 6
        else:
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
    hearing_summary = None
    if m.hearing:
        h = m.hearing
        hearing_summary = NewsMentionHearingSummaryOut(
            id=h.id, case_number=h.case_number, hearing_type_display=h.hearing_type_display,
            date=h.date, party_names=h.party_names,
        )
    return NewsMentionOut(
        id=m.id, article_url=m.article_url, source_name=m.source_name, headline=m.headline,
        published_at=m.published_at, match_status=m.match_status, source_type=m.source_type,
        hearing=hearing_summary,
    )


# Phase 8 doc: the review queue is now just the Tier 2 "weekly reading
# list" -- every row here already has its hearing_id set (the search
# that found it was for that specific hearing), so there's no more
# "which hearing does this belong to" ambiguity to resolve, only a
# relevance judgment (confirm/dismiss, below).
@router.get("/review-queue/news-mentions", response_model=list[NewsMentionOut])
def review_queue_news_mentions(db: Session = Depends(get_db), admin: AdminUser = Depends(get_current_admin)):
    mentions = (
        db.query(NewsMention)
        .filter(NewsMention.match_status == MatchStatus.in_weekly_reading_list)
        .order_by(NewsMention.fetched_at.desc())
        .all()
    )
    return [_news_mention_out(m) for m in mentions]


@router.get("/review-queue/news-mentions/count")
def review_queue_news_mentions_count(db: Session = Depends(get_db), admin: AdminUser = Depends(get_current_admin)):
    """A visible count, not just a list you have to open to notice."""
    count = db.query(NewsMention).filter(NewsMention.match_status == MatchStatus.in_weekly_reading_list).count()
    return {"count": count}


@router.get("/news-mentions/auto-matched", response_model=list[NewsMentionOut])
def auto_matched_news_mentions(db: Session = Depends(get_db), admin: AdminUser = Depends(get_current_admin)):
    """Phase 8 doc, Section 4's "log every run" transparency ask, as a
    read-only admin list: Tier 1 hits need no human review (a case
    number match is unambiguous), but a curator should still be able to
    see what's been auto-attached recently. No actions here -- if one's
    wrong, that's a data problem with the search result itself, not
    something confirm/dismiss on the reading list was ever meant to fix."""
    mentions = (
        db.query(NewsMention)
        .filter(NewsMention.match_status == MatchStatus.auto_matched)
        .order_by(NewsMention.fetched_at.desc())
        .limit(50)
        .all()
    )
    return [_news_mention_out(m) for m in mentions]


@router.post("/news-mentions/{mention_id}/confirm", response_model=NewsMentionOut)
def confirm_news_mention(mention_id: str, db: Session = Depends(get_db),
                          admin: AdminUser = Depends(get_current_admin)):
    """Phase 8 doc: confirms *relevance* -- "yes, this article is
    genuinely worth linking to this case" -- not "which hearing" (that
    was never ambiguous; the search was already run for this specific
    hearing). Promotes to manually_linked, which is what makes it count
    toward Hearing.has_news_mention and show up publicly."""
    mention = db.query(NewsMention).filter(NewsMention.id == mention_id).first()
    if not mention:
        raise HTTPException(404, "News mention not found")
    if mention.match_status != MatchStatus.in_weekly_reading_list:
        raise HTTPException(400, "This mention isn't in the weekly reading list")
    mention.match_status = MatchStatus.manually_linked
    _log(db, admin, "confirmed_news_mention", "news_mention", mention.id,
         f"confirmed relevance for hearing {mention.hearing.case_number if mention.hearing else '?'}")
    db.commit()
    db.refresh(mention)
    return _news_mention_out(mention)


@router.post("/news-mentions/{mention_id}/dismiss", response_model=NewsMentionOut)
def dismiss_news_mention(mention_id: str, db: Session = Depends(get_db),
                          admin: AdminUser = Depends(get_current_admin)):
    """A human looked at a reading-list item and said "not relevant."
    Sets match_status rather than deleting the row -- deleting it would
    let app/jobs/news_search.py's cadence re-search this hearing and
    re-surface the same dismissed article all over again; a dismissed
    row is what marks this hearing "resolved" for that purpose."""
    mention = db.query(NewsMention).filter(NewsMention.id == mention_id).first()
    if not mention:
        raise HTTPException(404, "News mention not found")
    if mention.match_status != MatchStatus.in_weekly_reading_list:
        raise HTTPException(400, "This mention isn't in the weekly reading list")
    mention.match_status = MatchStatus.dismissed
    _log(db, admin, "dismissed_news_mention", "news_mention", mention.id, mention.headline)
    db.commit()
    db.refresh(mention)
    return _news_mention_out(mention)


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


# Page-redesign doc: the homepage's "This Week's Pick" spotlight, as a
# real Editor choice rather than the client-side heuristic Home.jsx used
# before this existed (soonest hearing with a curated_blurb). Exactly one
# hearing is ever the pick -- clearing every other row in the same
# transaction, rather than a DB constraint, is this project's established
# way of enforcing a "single current thing" invariant (see
# NewsMention's soft-dedup docstring for the same reasoning applied
# elsewhere).
@router.post("/hearings/{hearing_id}/set-weekly-pick")
def set_weekly_pick(hearing_id: str, db: Session = Depends(get_db),
                     admin: AdminUser = Depends(require_editor)):
    hearing = db.query(Hearing).filter(Hearing.id == hearing_id).first()
    if not hearing:
        raise HTTPException(404, "Hearing not found")
    # Oct 2026 review, Phase 2 item 2: "This Week's Pick" is a spotlight
    # meant to get someone to actually go sit in on a hearing -- a
    # remote one isn't something a visitor can show up and watch, so
    # it was never a sensible answer to "what should I go see this
    # week," even though nothing previously stopped an Editor from
    # picking one by mistake.
    if hearing.appearance_type != AppearanceType.in_person:
        raise HTTPException(400, "Only an in-person hearing can be the weekly pick -- visitors can't attend a remote one.")
    db.query(Hearing).filter(Hearing.is_weekly_pick.is_(True)).update({"is_weekly_pick": False})
    hearing.is_weekly_pick = True
    _log(db, admin, "set_weekly_pick", "hearing", hearing.id, hearing.case_number)
    db.commit()
    return {"status": "updated"}


@router.post("/hearings/{hearing_id}/clear-weekly-pick")
def clear_weekly_pick(hearing_id: str, db: Session = Depends(get_db),
                       admin: AdminUser = Depends(require_editor)):
    hearing = db.query(Hearing).filter(Hearing.id == hearing_id).first()
    if not hearing:
        raise HTTPException(404, "Hearing not found")
    hearing.is_weekly_pick = False
    _log(db, admin, "clear_weekly_pick", "hearing", hearing.id, hearing.case_number)
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

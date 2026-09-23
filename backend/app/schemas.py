"""Pydantic response/request models for the API."""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.auth import validate_password_strength

# Phase-4 doc, Section 2.2: "enforce reasonable length limits on all text
# fields" -- applies to every email field in this file, not just the
# ones already covered (invite/reset flows). Deliberately a practical
# format check (has an @, something on each side, a dot after the @)
# rather than a full RFC 5322 grammar or an added email-validator
# dependency -- this is input hygiene against garbage/abuse, not the
# thing that confirms an address is real (only actually receiving mail
# there does that).
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_EMAIL_MAX_LENGTH = 320  # matches every `email` column's String(320) in app/models.py


def validate_email_format(value: str) -> str:
    stripped = (value or "").strip()
    if len(stripped) > _EMAIL_MAX_LENGTH:
        raise ValueError(f"Email must be under {_EMAIL_MAX_LENGTH} characters")
    if not _EMAIL_RE.match(stripped):
        raise ValueError("Enter a valid email address")
    return stripped
from app.models import (
    AcademicPeriodType,
    AppearanceType,
    ArchiveSubmitterRole,
    AttendanceStatus,
    CaseCategory,
    CourtLocation,
    HearingSource,
    HearingStatus,
    HearingTypeCategory,
    LivestreamSourceType,
    MatchConfidence,
    MatchStatus,
    ProceedingStage,
    ReportTargetType,
    SubmissionStatus,
    SubscriptionFilterType,
    SubscriptionFrequency,
)


class LinkNewsMentionIn(BaseModel):
    """Phase-6 doc, Section 4: link by case number directly from the
    queue, not just a raw hearing UUID (still supported for the rare
    case a curator already knows it)."""
    hearing_id: Optional[str] = None
    case_number: Optional[str] = None


class SuggestedHearingOut(BaseModel):
    """The candidate hearing a suggested_pending_review NewsMention is
    proposing -- shown directly in the review queue (Phase-6 doc, Section
    4) so confirming/rejecting doesn't need a second lookup."""
    id: str
    case_number: str
    hearing_type_display: str
    date: date
    party_names: list[str] = []

    @field_validator("party_names", mode="before")
    @classmethod
    def _parse_party_names(cls, value):
        if isinstance(value, str):
            return json.loads(value) if value else []
        return value or []


class NewsMentionOut(BaseModel):
    """Phase-6 doc, Section 1: extracted_case_numbers/
    extracted_party_candidates/match_confidence/match_signals are exactly
    the diagnosis this phase started from not having visible anywhere --
    exposed here (Editor-only; this schema is never used on a public
    endpoint) rather than left sitting in the DB unexamined."""
    model_config = ConfigDict(from_attributes=True)
    id: str
    article_url: str
    source_name: str
    headline: str
    published_at: Optional[datetime]
    match_status: MatchStatus
    match_confidence: Optional[MatchConfidence] = None
    extracted_case_numbers: list[str] = []
    extracted_party_candidates: list[str] = []
    match_signals: Optional[dict] = None
    suggested_hearing: Optional[SuggestedHearingOut] = None

    @field_validator("extracted_case_numbers", "extracted_party_candidates", mode="before")
    @classmethod
    def _parse_json_list(cls, value):
        if isinstance(value, str):
            return json.loads(value) if value else []
        return value or []

    @field_validator("match_signals", mode="before")
    @classmethod
    def _parse_json_object(cls, value):
        if isinstance(value, str):
            return json.loads(value) if value else None
        return value


class CommunitySubmissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    summary_text: Optional[str]
    judge_name: Optional[str]
    status: SubmissionStatus
    submitted_at: datetime
    # submitter_context is deliberately excluded -- reviewer-only, see
    # app/models.py::CommunitySubmission.


class JusticeOut(BaseModel):
    """Shared shape for the public roster (GET /api/justices, used both by
    the attendance UI's name list and the "Meet the Justices" directory)
    and an individual profile page (GET /api/justices/{id}) -- same
    fields either way, Section 3 just renders more of them on the
    individual page. photo_url is None when no photo's been uploaded;
    the raw bytes are never inlined here, only fetched via the dedicated
    endpoint the URL points at."""
    id: str
    display_name: str
    title: Optional[str] = None
    bio: Optional[str] = None
    year_or_major: Optional[str] = None
    why_care: Optional[str] = None
    fun_fact: Optional[str] = None
    photo_url: Optional[str] = None


class AttendanceOut(BaseModel):
    """Built explicitly in the router (not via model_validate) since it
    flattens fields from the related AdminUser (justice) row -- see
    routers/justices.py."""
    justice_id: str
    display_name: str
    title: Optional[str] = None
    status: AttendanceStatus
    note: Optional[str] = None
    updated_at: datetime


class AttendanceIn(BaseModel):
    # No justice_id here -- identity comes from the Justice login
    # (require_justice in routers/justices.py), not a caller-supplied
    # field. Earlier build session made this endpoint fully open with
    # justice_id in the body; reversed on request.
    status: AttendanceStatus
    note: Optional[str] = None

    @field_validator("note")
    @classmethod
    def _cap_length(cls, value):
        if value and len(value) > 500:
            raise ValueError("note must be under 500 characters")
        return value


class RecommendationIn(BaseModel):
    hearing_id: str
    # Required, not optional -- "a Justice can submit a starred
    # recommendation on any hearing with a short required reason."
    note: str

    @field_validator("note")
    @classmethod
    def _cap_length(cls, value):
        stripped = (value or "").strip()
        if not stripped:
            raise ValueError("A reason is required")
        if len(stripped) > 2000:
            raise ValueError("note must be under 2000 characters")
        return stripped


class RecommendationOut(BaseModel):
    id: str
    hearing_id: str
    hearing_case_number: str
    hearing_type_display: str
    hearing_date: date
    justice_id: str
    justice_display_name: str
    justice_title: Optional[str] = None
    note: Optional[str] = None
    created_at: datetime


class HearingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    source: HearingSource
    case_number: str
    case_category: CaseCategory
    party_names: list[str] = []
    hearing_type_raw: str
    hearing_type_display: str
    hearing_type_category: HearingTypeCategory
    date: date
    time: Optional[str]
    duration: Optional[str]
    court_location: CourtLocation
    courtroom: Optional[str]
    judge_name: Optional[str]
    livestream_source_type: LivestreamSourceType
    livestream_url: Optional[str]
    appearance_type: AppearanceType
    is_excluded: bool
    curated_blurb: Optional[str]
    status: HearingStatus
    change_note: Optional[str]
    first_seen_at: datetime
    last_verified_at: datetime
    attendance: list[AttendanceOut] = []
    news_mentions: list[NewsMentionOut] = []
    community_submissions: list[CommunitySubmissionOut] = []

    @field_validator("party_names", mode="before")
    @classmethod
    def _parse_party_names(cls, value):
        # Hearing.party_names is stored as a JSON-encoded string column
        # (see app/models.py); decode it here so API consumers always see
        # a real list.
        if isinstance(value, str):
            return json.loads(value) if value else []
        return value or []

    @field_validator("attendance", mode="before")
    @classmethod
    def _flatten_attendance(cls, value):
        # Hearing.attendance is a list of HearingAttendance ORM rows, each
        # with a `.justice` relationship -- flatten the fields AttendanceOut
        # actually needs (display_name, title) rather than exposing the raw
        # join, and skip any row whose justice account somehow got
        # deactivated/deleted out from under it.
        flattened = []
        for row in value or []:
            if isinstance(row, dict):
                flattened.append(row)
                continue
            if not getattr(row, "justice", None):
                continue
            flattened.append({
                "justice_id": row.justice_id,
                "display_name": row.justice.display_name or row.justice.email,
                "title": row.justice.title,
                "status": row.status,
                "note": row.note,
                "updated_at": row.updated_at,
            })
        return flattened

    @field_validator("community_submissions", mode="before")
    @classmethod
    def _only_approved(cls, value):
        # The public API (and this schema is used for both public and admin
        # hearing responses) should only ever surface APPROVED community
        # submissions -- pending/rejected ones stay in the admin review
        # queue endpoints only. Filtering here (rather than trusting every
        # call site to remember) is the belt-and-suspenders choice given
        # Section 4's guardrails around public-facing content.
        items = list(value or [])
        return [s for s in items if getattr(s, "status", None) == SubmissionStatus.approved
                or (isinstance(s, dict) and s.get("status") == SubmissionStatus.approved)]

    @classmethod
    def from_orm_hearing(cls, hearing) -> "HearingOut":
        return cls.model_validate(hearing)


class SubscriptionCreate(BaseModel):
    email: str
    filter_type: SubscriptionFilterType
    filter_value: str
    frequency: SubscriptionFrequency

    @field_validator("email")
    @classmethod
    def _valid_email(cls, value):
        return validate_email_format(value)

    @field_validator("filter_value")
    @classmethod
    def _cap_filter_value(cls, value):
        if value and len(value) > 255:  # matches Subscription.filter_value's String(255)
            raise ValueError("filter_value must be under 255 characters")
        return value


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    filter_type: SubscriptionFilterType
    filter_value: str
    frequency: SubscriptionFrequency
    unsubscribe_token: str


class DataStatusOut(BaseModel):
    """Phase-2 doc, Section 1: "Last updated HH:MM today" + refresh-button
    state, computed from real JobRun rows."""
    last_updated_at: Optional[datetime]
    next_refresh_available_at: Optional[datetime]
    refresh_cooldown_minutes: int


class AcademicCalendarPeriodIn(BaseModel):
    label: str
    start_date: date
    end_date: date
    type: AcademicPeriodType


class AcademicCalendarPeriodOut(AcademicCalendarPeriodIn):
    model_config = ConfigDict(from_attributes=True)
    id: str


class AdminLoginRequest(BaseModel):
    email: str
    password: str
    # Present only when the account has 2FA enabled (Phase-4 doc, Section
    # 2.3) -- see routers/admin.py::login for the two-step flow this
    # supports without a separate endpoint.
    totp_code: Optional[str] = None

    @field_validator("email")
    @classmethod
    def _valid_email(cls, value):
        return validate_email_format(value)


class AdminLoginResponse(BaseModel):
    access_token: str
    id: str
    role: Optional[str] = None
    is_justice: bool = False
    display_name: Optional[str] = None
    title: Optional[str] = None


class BlurbDraftIn(BaseModel):
    curated_blurb_draft: str


class ExclusionIn(BaseModel):
    is_excluded: bool
    exclusion_reason: Optional[str] = None


class AppellateCandidateOut(BaseModel):
    case_name: str
    court: str
    date_filed: Optional[str]
    docket_number: Optional[str]
    absolute_url: str
    result_type: str
    already_in_news: bool = False


class CommunitySubmissionIn(BaseModel):
    summary_text: Optional[str] = None
    judge_name: Optional[str] = None
    submitter_context: Optional[str] = None
    # Honeypot: real users never see or fill this field (hidden via CSS in
    # the frontend form); a filled value is a strong bot signal. Not a
    # robust anti-abuse measure on its own, just a cheap first filter --
    # see routers/public.py.
    website: Optional[str] = None

    @field_validator("summary_text", "judge_name", "submitter_context")
    @classmethod
    def _cap_length(cls, value, info):
        limits = {"summary_text": 2000, "judge_name": 120, "submitter_context": 500}
        limit = limits[info.field_name]
        if value and len(value) > limit:
            raise ValueError(f"{info.field_name} must be under {limit} characters")
        return value


class CommunitySubmissionReviewOut(CommunitySubmissionOut):
    submitter_context: Optional[str]
    hearing_id: str
    hearing_case_number: str


class PublishAppellateCandidateIn(BaseModel):
    case_name: str
    docket_number: str
    court_location: CourtLocation
    court_note: str
    date: date
    time: Optional[str] = None
    hearing_type_raw: str
    # Real bug caught by hand-publishing real Colorado Supreme Court cases:
    # this used to be hardcoded to `civil` for every appellate publish,
    # which is simply wrong for a criminal appeal (the majority of the
    # real September 2026 docket, for instance). CourtListener's search
    # result doesn't reliably expose this, so it's the curator's call, not
    # an auto-detected field -- same reasoning as case_category being a
    # judgment call for the county docket's own ambiguous prefixes.
    case_category: CaseCategory = CaseCategory.civil
    curated_blurb: Optional[str] = None
    source_url: str
    # Optional override for a federal case with a known public audio-access
    # line -- federal courts don't offer general video livestreaming, so
    # there's no default URL to assume (see app/livestream.py); leave blank
    # unless the curator has a specific one for this case.
    federal_audio_line_url: Optional[str] = None


class ArchiveEntryIn(BaseModel):
    hearing_id: str
    proceeding_stage: ProceedingStage
    judge_name: Optional[str] = None
    reflection_text: Optional[str] = None
    submitted_by_name: str
    # Honeypot, same pattern as CommunitySubmissionIn -- real visitors
    # never see or fill this field.
    website: Optional[str] = None

    @field_validator("submitted_by_name")
    @classmethod
    def _name_required(cls, value):
        stripped = (value or "").strip()
        if not stripped:
            raise ValueError("A name is required")
        if len(stripped) > 120:
            raise ValueError("Name must be under 120 characters")
        return stripped

    @field_validator("judge_name")
    @classmethod
    def _cap_judge_name(cls, value):
        if value and len(value) > 120:
            raise ValueError("judge_name must be under 120 characters")
        return value

    @field_validator("reflection_text")
    @classmethod
    def _cap_reflection(cls, value):
        if value and len(value) > 5000:
            raise ValueError("reflection_text must be under 5000 characters")
        return value


class ArchiveEntryUpdateIn(BaseModel):
    """Justice-only edit -- see routers/archive.py. All fields optional;
    only what's provided gets changed."""
    proceeding_stage: Optional[ProceedingStage] = None
    judge_name: Optional[str] = None
    reflection_text: Optional[str] = None
    attendees: Optional[list[str]] = None


class AttendeeOut(BaseModel):
    """Phase-3 doc, Section 4: an Archive entry's attendee list should
    link to a Justice's profile wherever the name is recognized as one.
    `attendees` is still stored as plain display-name strings (see
    ArchiveEntry.attendees and ArchiveEntryUpdateIn -- a Justice editing
    the list can still type any name, including a non-Justice's), so
    `justice_id` here is resolved at read time by matching the name
    against the current roster (routers/archive.py::_resolve_attendees) --
    None when it doesn't match a real Justice, which just renders as
    plain, unlinked text."""
    name: str
    justice_id: Optional[str] = None


class ArchiveEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    hearing_id: str
    hearing_case_number: str
    hearing_type_display: str
    hearing_date: date
    case_category: CaseCategory
    proceeding_stage: ProceedingStage
    judge_name: Optional[str] = None
    attendees: list[AttendeeOut] = []
    reflection_text: Optional[str] = None
    submitted_by_name: str
    submitted_by_role: ArchiveSubmitterRole
    # Set only for entries created via the "Mark Attendance" path after
    # this field existed -- see ArchiveEntry.submitted_by_justice_id.
    submitted_by_justice_id: Optional[str] = None
    created_at: datetime
    # submitter_ip deliberately excluded -- internal-only, see
    # ArchiveEntry's docstring in app/models.py.


# --- Phase-3 doc, Sections 1-3: invites, password reset, profiles ----------

class InviteCreateIn(BaseModel):
    email: str
    display_name: str
    title: Optional[str] = None

    @field_validator("email")
    @classmethod
    def _valid_email(cls, value):
        return validate_email_format(value)

    @field_validator("display_name")
    @classmethod
    def _require_name(cls, value):
        stripped = (value or "").strip()
        if not stripped:
            raise ValueError("A name is required")
        if len(stripped) > 120:
            raise ValueError("Name must be under 120 characters")
        return stripped


class InviteOut(BaseModel):
    """Returned to the inviting Editor only. invite_link is included
    directly (not just emailed) so provisioning still works end-to-end
    today, before a real transactional-email account exists (see
    EMAIL_BACKEND in app/config.py) -- an Editor can copy/paste it by
    hand. Safe: only an authenticated Editor/Justice ever sees this
    response."""
    email: str
    display_name: str
    expires_at: datetime
    invite_link: str


class AllowlistEntryIn(BaseModel):
    """Adds an email to JusticeAllowlistEntry (app/models.py) -- the gate
    behind the self-service POST /api/justices/request-invite. Same
    shape/validation as InviteCreateIn since it's the same underlying
    information (who's allowed to become a Justice and what to call
    them), just not sent anywhere yet."""
    email: str
    display_name: str
    title: Optional[str] = None

    @field_validator("email")
    @classmethod
    def _valid_email(cls, value):
        return validate_email_format(value)

    @field_validator("display_name")
    @classmethod
    def _require_name(cls, value):
        stripped = (value or "").strip()
        if not stripped:
            raise ValueError("A name is required")
        if len(stripped) > 120:
            raise ValueError("Name must be under 120 characters")
        return stripped


class AllowlistEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    display_name: str
    title: Optional[str] = None
    created_at: datetime


class RequestInviteIn(BaseModel):
    """Public: what a Justice submits on the self-service 'get my signup
    link' page."""
    email: str

    @field_validator("email")
    @classmethod
    def _valid_email(cls, value):
        return validate_email_format(value)


class InviteInfoOut(BaseModel):
    """Public: what the accept-invite page shows before a password is
    set. No token, no internal fields -- just enough to say "you've been
    invited as ___" back to whoever opened the link."""
    email: str
    display_name: str
    title: Optional[str] = None
    expires_at: datetime


class InviteAcceptIn(BaseModel):
    password: str

    @field_validator("password")
    @classmethod
    def _strong_password(cls, value):
        return validate_password_strength(value)


class ForgotPasswordIn(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def _valid_email(cls, value):
        return validate_email_format(value)


class ResetPasswordIn(BaseModel):
    password: str

    @field_validator("password")
    @classmethod
    def _strong_password(cls, value):
        return validate_password_strength(value)


class JusticeProfileIn(BaseModel):
    """A Justice editing their own profile (routers/account.py) -- every
    field optional so a partial save (e.g. just the bio) doesn't require
    resending everything else. Length caps are the server-side half of
    Section 5's "sanitize free-text fields" -- the actual XSS defense is
    React's default escaping on render (same reasoning as the Archive's
    reflection_text, see docs/SECURITY_REVIEW.md); these caps just keep a
    profile from becoming an unbounded wall of text."""
    bio: Optional[str] = None
    year_or_major: Optional[str] = None
    why_care: Optional[str] = None
    fun_fact: Optional[str] = None

    @field_validator("bio", "why_care")
    @classmethod
    def _cap_long_field(cls, value):
        if value and len(value) > 2000:
            raise ValueError("Must be under 2000 characters")
        return value

    @field_validator("year_or_major")
    @classmethod
    def _cap_year_or_major(cls, value):
        if value and len(value) > 120:
            raise ValueError("Must be under 120 characters")
        return value

    @field_validator("fun_fact")
    @classmethod
    def _cap_fun_fact(cls, value):
        if value and len(value) > 300:
            raise ValueError("Must be under 300 characters")
        return value


# --- Phase-4 doc, Section 2.3: two-factor authentication --------------------

class TotpSetupOut(BaseModel):
    """The secret is included alongside the QR code for manual entry
    (some authenticator apps/situations don't support scanning) -- not a
    security regression, since 2FA isn't active at all until
    POST /api/account/2fa/confirm proves the account holder actually has
    it working."""
    secret: str
    provisioning_uri: str
    qr_code_data_uri: str


class TotpConfirmIn(BaseModel):
    code: str


class TotpConfirmOut(BaseModel):
    """backup_codes is shown exactly once -- only the hash is ever
    persisted (see app/totp.py). Losing them means falling back to an
    Editor resetting the account, same as losing a password."""
    backup_codes: list[str]


class TotpDisableIn(BaseModel):
    """Requires the current password, not just an authenticated session --
    turning off 2FA is a real reduction in an account's security, worth
    the same confirmation a password change would get."""
    password: str


# --- Phase-4 doc, Section 2.5: "Report" flagging ----------------------------

class ReportIn(BaseModel):
    target_type: ReportTargetType
    target_id: str
    reason: Optional[str] = None
    # Honeypot, same pattern as ArchiveEntryIn/CommunitySubmissionIn.
    website: Optional[str] = None

    @field_validator("reason")
    @classmethod
    def _cap_reason(cls, value):
        if value and len(value) > 1000:
            raise ValueError("reason must be under 1000 characters")
        return value


class ReportQueueOut(BaseModel):
    """What an Editor sees in the dashboard's Reports queue -- includes
    enough of the reported content (target_summary) to triage without a
    separate lookup, but never reporter_ip (internal-only, see
    ContentReport's docstring in app/models.py)."""
    model_config = ConfigDict(from_attributes=True)
    id: str
    target_type: ReportTargetType
    target_id: str
    reason: Optional[str] = None
    resolved: bool
    created_at: datetime
    target_summary: Optional[str] = None
    target_url: Optional[str] = None

"""Pydantic response/request models for the API."""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.auth import validate_password_strength
from app.availability import NUM_SLOTS, WEEKDAY_ABBRS

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
    MatchStatus,
    ProceedingStage,
    ReportTargetType,
    SourceType,
    SubmissionStatus,
    SubscriptionFilterType,
    SubscriptionFrequency,
)


class NewsMentionHearingSummaryOut(BaseModel):
    """Phase 8 doc: the hearing a NewsMention belongs to -- shown
    alongside every Tier 2 "weekly reading list" item so a curator has
    full context (case number, date, parties) without a second lookup.
    Renamed from the Phase-6 doc's SuggestedHearingOut, same shape: a
    Tier-2 item's hearing context is exactly as useful to show as the
    old suggested-match candidate was, it's just never ambiguous now.

    from_attributes=True is required here, not just on the outer
    NewsMentionOut: a real crash caught in local testing -- the public
    GET /api/hearings/{id} endpoint 500'd on any hearing with a
    confirmed news mention, because NewsMentionOut.hearing reads
    NewsMention.hearing (an ORM relationship, i.e. a raw Hearing object)
    and pydantic v2 does not propagate from_attributes into a nested
    submodel's own validation just because the outer model has it."""
    model_config = ConfigDict(from_attributes=True)
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
    """Phase 8 doc: a deterministic case-number-found-or-not model has no
    confidence tier or diagnosis-signals concept left to expose -- the
    Phase-6 doc's extracted_case_numbers/extracted_party_candidates/
    match_confidence/match_signals fields are gone. source_type replaces
    them as the one piece of "how was this found" context worth keeping."""
    model_config = ConfigDict(from_attributes=True)
    id: str
    article_url: str
    source_name: str
    headline: str
    published_at: Optional[datetime]
    match_status: MatchStatus
    source_type: Optional[SourceType] = None
    hearing: Optional[NewsMentionHearingSummaryOut] = None


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
    hearing_tag_color: str = "other"
    hearing_date: date
    justice_id: str
    justice_display_name: str
    justice_title: Optional[str] = None
    note: Optional[str] = None
    created_at: datetime
    is_pinned: bool = False


MAX_EXTERNAL_LINKS = 10


class ExternalLinkIn(BaseModel):
    """Phase 9 doc: one {label, url} entry in a LearnTopic/CaseTeachingNote's
    external_links list -- stored JSON-encoded (Hearing.party_names'
    convention), validated as a real list of these shapes on the way in."""
    label: str
    url: str

    @field_validator("label")
    @classmethod
    def _cap_label(cls, value):
        stripped = (value or "").strip()
        if not stripped:
            raise ValueError("A label is required for each link")
        if len(stripped) > 120:
            raise ValueError("Link label must be under 120 characters")
        return stripped

    @field_validator("url")
    @classmethod
    def _valid_url(cls, value):
        stripped = (value or "").strip()
        if not stripped.startswith(("http://", "https://")):
            raise ValueError("Link URL must start with http:// or https://")
        if len(stripped) > 500:
            raise ValueError("Link URL must be under 500 characters")
        return stripped


class ExternalLinkOut(BaseModel):
    label: str
    url: str


def parse_external_links(value):
    if isinstance(value, str):
        return json.loads(value) if value else []
    return value or []


def _validate_body_text(value: str, field_name: str, max_length: int = 5000) -> str:
    stripped = (value or "").strip()
    if not stripped:
        raise ValueError(f"{field_name} is required")
    if len(stripped) > max_length:
        raise ValueError(f"{field_name} must be under {max_length} characters")
    return stripped


class LearnTopicIn(BaseModel):
    """Phase 9 doc: create/replace-everything-but-video for a LearnTopic.
    At least one of the two matching dimensions must be set -- enforced
    here (a ValueError from a model_validator becomes a 422, same as any
    other field_validator failure) rather than in the DB, since "matches
    nothing" isn't a shape the database itself can express as a
    constraint without a lot of ceremony for one rule."""
    title: str
    applies_to_hearing_type_category: Optional[HearingTypeCategory] = None
    applies_to_case_category: Optional[CaseCategory] = None
    body_text: str
    video_url: Optional[str] = None
    external_links: list[ExternalLinkIn] = []

    @field_validator("title")
    @classmethod
    def _cap_title(cls, value):
        stripped = (value or "").strip()
        if not stripped:
            raise ValueError("A title is required")
        if len(stripped) > 200:
            raise ValueError("Title must be under 200 characters")
        return stripped

    @field_validator("body_text")
    @classmethod
    def _cap_body(cls, value):
        return _validate_body_text(value, "body_text")

    @field_validator("external_links")
    @classmethod
    def _cap_links(cls, value):
        if len(value) > MAX_EXTERNAL_LINKS:
            raise ValueError(f"At most {MAX_EXTERNAL_LINKS} external links")
        return value

    @model_validator(mode="after")
    def _at_least_one_dimension(self):
        if not self.applies_to_hearing_type_category and not self.applies_to_case_category:
            raise ValueError("Set at least one of hearing type or case category, or this topic would never match anything")
        return self


class LearnTopicUpdateIn(BaseModel):
    """All fields optional -- only what's provided gets changed, same
    pattern as ArchiveEntryUpdateIn."""
    title: Optional[str] = None
    applies_to_hearing_type_category: Optional[HearingTypeCategory] = None
    applies_to_case_category: Optional[CaseCategory] = None
    body_text: Optional[str] = None
    video_url: Optional[str] = None
    external_links: Optional[list[ExternalLinkIn]] = None


class LearnTopicOut(BaseModel):
    id: str
    title: str
    applies_to_hearing_type_category: Optional[HearingTypeCategory] = None
    applies_to_case_category: Optional[CaseCategory] = None
    body_text: str
    video_url: Optional[str] = None
    has_uploaded_video: bool = False
    external_links: list[ExternalLinkOut] = []
    created_by_display_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class CaseTeachingNoteIn(BaseModel):
    body_text: str
    video_url: Optional[str] = None
    external_links: list[ExternalLinkIn] = []

    @field_validator("body_text")
    @classmethod
    def _cap_body(cls, value):
        return _validate_body_text(value, "body_text")

    @field_validator("external_links")
    @classmethod
    def _cap_links(cls, value):
        if len(value) > MAX_EXTERNAL_LINKS:
            raise ValueError(f"At most {MAX_EXTERNAL_LINKS} external links")
        return value


class CaseTeachingNoteUpdateIn(BaseModel):
    body_text: Optional[str] = None
    video_url: Optional[str] = None
    external_links: Optional[list[ExternalLinkIn]] = None


class CaseTeachingNoteOut(BaseModel):
    id: str
    hearing_id: str
    body_text: str
    video_url: Optional[str] = None
    has_uploaded_video: bool = False
    external_links: list[ExternalLinkOut] = []
    created_by_display_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class CopyToArchiveIn(BaseModel):
    """Phase 9 doc: "Copy to Archive" -- reflection_text comes from the
    note itself (not re-typed here), but proceeding_stage has no
    equivalent on a CaseTeachingNote (it describes what was witnessed at
    a specific attended hearing, which a teaching note doesn't imply),
    so the Justice picks one at copy time rather than it being guessed."""
    proceeding_stage: ProceedingStage


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
    tag_color: str = "other"
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
    is_weekly_pick: bool = False
    curated_blurb: Optional[str]
    status: HearingStatus
    change_note: Optional[str]
    first_seen_at: datetime
    last_verified_at: datetime
    attendance: list[AttendanceOut] = []
    news_mentions: list[NewsMentionOut] = []
    community_submissions: list[CommunitySubmissionOut] = []
    # Phase 9 doc: teaching_notes is a real relationship (flattened the
    # same way _flatten_attendance handles HearingAttendance's .justice
    # join below -- CaseTeachingNoteOut's created_by_display_name has no
    # same-named ORM attribute to auto-populate from). learn_topics is
    # NOT a relationship (LearnTopic matches by type/category, not a
    # stored FK -- see app/learn.py) -- routers/public.py and
    # routers/admin.py set it explicitly after construction; it's never
    # populated by from_attributes, which is why there's no matching
    # field_validator for it here.
    teaching_notes: list[CaseTeachingNoteOut] = []
    learn_topics: list[LearnTopicOut] = []

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

    @field_validator("teaching_notes", mode="before")
    @classmethod
    def _flatten_teaching_notes(cls, value):
        # Same reasoning as _flatten_attendance above: CaseTeachingNoteOut's
        # created_by_display_name has no identically-named ORM attribute
        # (only a .created_by relationship object) for from_attributes to
        # auto-populate, and video_data (raw bytes) should never reach
        # JSON at all -- has_uploaded_video is the honest stand-in.
        flattened = []
        for row in value or []:
            if isinstance(row, dict):
                flattened.append(row)
                continue
            flattened.append({
                "id": row.id,
                "hearing_id": row.hearing_id,
                "body_text": row.body_text,
                "video_url": row.video_url,
                "has_uploaded_video": bool(row.video_data),
                "external_links": parse_external_links(row.external_links),
                "created_by_display_name": (
                    (row.created_by.display_name or row.created_by.email) if row.created_by else None
                ),
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            })
        return flattened

    @field_validator("news_mentions", mode="before")
    @classmethod
    def _only_confirmed_news(cls, value):
        # Phase 8 doc: mirrors _only_approved below exactly. Without this,
        # a Tier 2 "weekly reading list" item (which -- unlike the old
        # Phase-6 "suggested" status -- always has hearing_id set from the
        # moment it's created, since the search that found it was already
        # for this specific hearing) would make the "In the news" badge/
        # filter on HearingList.jsx/HearingDetail.jsx fire for every
        # hearing with an unreviewed candidate, not just a confirmed one.
        # Filtering here keeps the embedded list itself the single source
        # of truth Hearing.has_news_mention already defines, so those two
        # frontend call sites' existing `.length > 0` checks need no
        # changes at all.
        confirmed = {MatchStatus.auto_matched, MatchStatus.manually_linked}

        def status_of(item):
            return item.get("match_status") if isinstance(item, dict) else getattr(item, "match_status", None)

        return [item for item in (value or []) if status_of(item) in confirmed]

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


class AvailabilityCell(BaseModel):
    """Phase-6.3 doc: one painted-free 30-min grid cell -- the exact same
    shape used by a Justice's own availability, a subscriber's personal-
    availability digest filter, and mirrored client-side
    (frontend/src/availabilitySlots.js) for the public, browser-local
    matching. Replaces the Phase-6.2 range-based AvailabilityBlock."""
    day_of_week: str
    slot_index: int

    @field_validator("day_of_week")
    @classmethod
    def _valid_day(cls, value):
        if value not in WEEKDAY_ABBRS:
            raise ValueError(f"day_of_week must be one of {WEEKDAY_ABBRS}")
        return value

    @field_validator("slot_index")
    @classmethod
    def _valid_slot(cls, value):
        if not (0 <= value < NUM_SLOTS):
            raise ValueError(f"slot_index must be between 0 and {NUM_SLOTS - 1}")
        return value


class SubscriptionCreate(BaseModel):
    email: str
    filter_type: SubscriptionFilterType
    filter_value: str
    frequency: SubscriptionFrequency
    # Only used (and required) when filter_type == personal_availability --
    # see the model validator below.
    availability_cells: Optional[list[AvailabilityCell]] = None

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

    @model_validator(mode="after")
    def _availability_only_for_personal(self):
        is_personal = self.filter_type == SubscriptionFilterType.personal_availability
        if is_personal and not self.availability_cells:
            raise ValueError("availability_cells is required for filter_type=personal_availability")
        if not is_personal and self.availability_cells:
            raise ValueError("availability_cells is only used with filter_type=personal_availability")
        return self


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    filter_type: SubscriptionFilterType
    filter_value: str
    frequency: SubscriptionFrequency
    unsubscribe_token: str
    # Populated by the router via app.availability_slots.load_owner_cells --
    # there's no JSON column behind this any more (see AvailabilitySlot in
    # app/models.py), so unlike Phase 6.2 there's no field_validator here
    # parsing a JSON string; the router always passes a real list.
    availability_cells: list[AvailabilityCell] = []


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
    hearing_tag_color: str = "other"
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


# --- Phase-6.2 doc, Section 4: Justice-only recurring availability ---------
# Deliberately separate from JusticeProfileIn/JusticeOut -- those are
# shared with (or the basis for) the public roster/profile response, and
# availability must never appear there (Section 4: "completely invisible
# to non-Justice/public users, both in the UI and in any API response").

class JusticeAvailabilityIn(BaseModel):
    """Full-replace semantics: send the complete current cell list, not
    an incremental add/remove."""
    cells: list[AvailabilityCell] = []

    @field_validator("cells")
    @classmethod
    def _cap_cell_count(cls, value):
        if len(value) > 7 * NUM_SLOTS:  # the entire grid, at most
            raise ValueError("Too many availability cells")
        return value


class JusticeAvailabilityOut(BaseModel):
    cells: list[AvailabilityCell] = []


class AvailabilitySummaryRequest(BaseModel):
    """The hearing_ids the frontend already has from its own
    GET /api/hearings call -- passed explicitly rather than a
    date_from/date_to range so this can never disagree with whatever
    filters (type/category/court/news-only) that other endpoint applied.
    See routers/account.py::hearings_availability_summary."""
    hearing_ids: list[str]

    @field_validator("hearing_ids")
    @classmethod
    def _cap_hearing_count(cls, value):
        if len(value) > 200:
            raise ValueError("Too many hearing_ids in one request")
        return value


class AvailabilitySummaryEntry(BaseModel):
    free_count: int
    total: int
    free_justice_names: list[str]
    time_known: bool


class TeamAvailabilityCell(BaseModel):
    """Phase-6.3 doc, Section 4: one cell of the "Team Availability"
    heatmap -- every one of the 7*NUM_SLOTS grid cells, precomputed
    server-side in one pass rather than the frontend re-deriving counts
    from raw per-Justice cells."""
    day_of_week: str
    slot_index: int
    free_count: int
    total: int
    free_justice_names: list[str]


class TeamAvailabilityOut(BaseModel):
    total_justices: int
    cells: list[TeamAvailabilityCell]


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

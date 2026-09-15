"""Pydantic response/request models for the API."""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator

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
    SubmissionStatus,
    SubscriptionFilterType,
    SubscriptionFrequency,
)


class NewsMentionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    article_url: str
    source_name: str
    headline: str
    published_at: Optional[datetime]
    match_status: MatchStatus


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
    id: str
    display_name: str
    title: Optional[str] = None


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


class AdminLoginResponse(BaseModel):
    access_token: str
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
    attendees: list[str] = []
    reflection_text: Optional[str] = None
    submitted_by_name: str
    submitted_by_role: ArchiveSubmitterRole
    created_at: datetime
    # submitter_ip deliberately excluded -- internal-only, see
    # ArchiveEntry's docstring in app/models.py.

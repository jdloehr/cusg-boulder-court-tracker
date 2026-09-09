"""
SQLAlchemy models for the CUSG Boulder Court Tracker.

Mirrors the data model in Section 6 of the build prompt. Written against
plain SQLAlchemy types (String/Text/Date/Time/Boolean/Enum) so the same
models run unmodified against SQLite (local dev, used for this demo) or
PostgreSQL (production - set DATABASE_URL, see app/config.py).
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------

class HearingSource(str, enum.Enum):
    state_docket_export = "state_docket_export"
    federal_courtlistener = "federal_courtlistener"
    manual = "manual"


class CaseCategory(str, enum.Enum):
    criminal = "criminal"
    misdemeanor = "misdemeanor"
    traffic = "traffic"
    civil = "civil"
    domestic_relations = "domestic_relations"
    probate = "probate"
    juvenile = "juvenile"  # tracked so it can be excluded by default, not shown
    other = "other"


class HearingTypeCategory(str, enum.Enum):
    jury_trial = "jury_trial"
    oral_argument_motions = "oral_argument_motions"
    other = "other"
    unrecognized = "unrecognized"  # schema-drift bucket, see hearing_types.py


class CourtLocation(str, enum.Enum):
    boulder_county = "boulder_county"
    boulder_district = "boulder_district"
    longmont_combined = "longmont_combined"
    us_district_colorado = "us_district_colorado"
    # Not in Section 6's original enum listing, added because the flagship
    # federal-supplement example the build prompt itself names (Suncor
    # Energy v. County Commissioners of Boulder County) is, as of this
    # build, pending oral argument at the U.S. Supreme Court rather than a
    # Colorado district court -- see docs/DATA_SOURCE_FINDINGS.md. Bucketing
    # it under us_district_colorado would misdescribe which court a student
    # would need to travel to (or watch remotely).
    us_supreme_court = "us_supreme_court"
    unknown = "unknown"


class AppearanceType(str, enum.Enum):
    in_person = "in_person"
    remote = "remote"
    unknown = "unknown"


class HearingStatus(str, enum.Enum):
    scheduled = "scheduled"
    changed = "changed"
    cancelled = "cancelled"


class MatchStatus(str, enum.Enum):
    auto_matched = "auto_matched"
    manually_linked = "manually_linked"
    unmatched_review = "unmatched_review"


class SubscriptionFilterType(str, enum.Enum):
    hearing_type_category = "hearing_type_category"
    case_number = "case_number"
    keyword = "keyword"


class SubscriptionFrequency(str, enum.Enum):
    weekly_digest = "weekly_digest"
    realtime_for_followed_case = "realtime_for_followed_case"


class AcademicPeriodType(str, enum.Enum):
    break_ = "break"
    finals = "finals"


class SubmissionStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class AdminRole(str, enum.Enum):
    editor = "editor"
    contributor = "contributor"


class AttendanceStatus(str, enum.Enum):
    attending = "attending"
    not_attending = "not_attending"
    maybe = "maybe"


# --------------------------------------------------------------------------
# Core tables
# --------------------------------------------------------------------------

class Hearing(Base):
    __tablename__ = "hearings"
    # No DB-level uniqueness constraint on the natural key: the docket export
    # has no persistent hearing ID, and the same (case_number,
    # hearing_type_raw) pair can legitimately recur (e.g. two separate
    # motions hearings on one case). Matching/diffing across pulls is
    # therefore an application-level heuristic -- see
    # jobs/docket_pull.py:match_existing_hearing() and the caveats
    # documented there and in docs/DATA_SOURCE_FINDINGS.md.

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    source: Mapped[HearingSource] = mapped_column(Enum(HearingSource), nullable=False)
    case_number: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    case_category: Mapped[CaseCategory] = mapped_column(Enum(CaseCategory), nullable=False)
    party_names: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON-encoded list

    hearing_type_raw: Mapped[str] = mapped_column(String(255), nullable=False)
    hearing_type_display: Mapped[str] = mapped_column(String(255), nullable=False)
    hearing_type_category: Mapped[HearingTypeCategory] = mapped_column(
        Enum(HearingTypeCategory), nullable=False, index=True
    )

    date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    time: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # "HH:MM" as printed by court
    duration: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    court_location: Mapped[CourtLocation] = mapped_column(Enum(CourtLocation), nullable=False, index=True)
    courtroom: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Not part of the docket export (Section 2.1's CSV has no judge column)
    # and not in the original Section 6 schema -- added so an approved
    # CommunitySubmission or an Editor's own knowledge has somewhere to go.
    # Always double-check against the official docket; a case can be
    # reassigned between when this is entered and when a student attends.
    judge_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)

    appearance_type: Mapped[AppearanceType] = mapped_column(
        Enum(AppearanceType), nullable=False, default=AppearanceType.unknown
    )

    is_excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    exclusion_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Published, publicly-visible "why watch this" text (Section 5.2).
    curated_blurb: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Not in Section 6's schema listing, added to actually implement Section
    # 5.4's Editor/Contributor split: a Contributor can draft a blurb here,
    # an Editor reviews it and calls PATCH .../publish-blurb to copy it into
    # curated_blurb (the field the public API/UI reads).
    curated_blurb_draft: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    status: Mapped[HearingStatus] = mapped_column(
        Enum(HearingStatus), nullable=False, default=HearingStatus.scheduled
    )
    # Free-text description of the most recent change, e.g. "moved from
    # 2026-09-15 09:00 to 2026-09-17 13:30" - shown next to the "changed" badge.
    change_note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    last_verified_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    news_mentions: Mapped[list["NewsMention"]] = relationship(back_populates="hearing")
    community_submissions: Mapped[list["CommunitySubmission"]] = relationship(back_populates="hearing")
    attendance: Mapped[list["HearingAttendance"]] = relationship(back_populates="hearing")
    recommendations: Mapped[list["HearingRecommendation"]] = relationship(back_populates="hearing")

    @property
    def has_news_mention(self) -> bool:
        return any(nm.match_status != MatchStatus.unmatched_review for nm in self.news_mentions)


class NewsMention(Base):
    __tablename__ = "news_mentions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    hearing_id: Mapped[Optional[str]] = mapped_column(ForeignKey("hearings.id"), nullable=True, index=True)

    article_url: Mapped[str] = mapped_column(String(1000), nullable=False, unique=True)
    source_name: Mapped[str] = mapped_column(String(120), nullable=False)
    headline: Mapped[str] = mapped_column(String(500), nullable=False)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # What the extraction pipeline found, kept for reviewer transparency.
    extracted_case_numbers: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list
    extracted_party_candidates: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list

    match_status: Mapped[MatchStatus] = mapped_column(Enum(MatchStatus), nullable=False, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    hearing: Mapped["Optional[Hearing]"] = relationship(back_populates="news_mentions")


class CommunitySubmission(Base):
    """Public "add details about this case" submissions (e.g. a case
    summary, a judge's name) -- not in the original Section 6 schema,
    added on request. Deliberately moderated rather than published
    immediately: this site is fully public/unauthenticated (Section 7),
    and Section 4's guardrails around not exposing more than the docket
    itself does and applying judgment to sensitive content apply just as
    much to what a random visitor submits as to what the automated
    pipelines pull in. A submission only reaches judge_name/public display
    after an Editor approves it -- see EXCLUSION_LOGIC.md."""
    __tablename__ = "community_submissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    hearing_id: Mapped[str] = mapped_column(ForeignKey("hearings.id"), nullable=False, index=True)

    summary_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    judge_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    # Optional, unverified free-text context from the submitter (e.g. "I
    # was in the gallery for this" or an email if they want a reply) --
    # never shown publicly, for the review team's eyes only.
    submitter_context: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    status: Mapped[SubmissionStatus] = mapped_column(
        Enum(SubmissionStatus), nullable=False, default=SubmissionStatus.pending, index=True
    )
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    submitted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    hearing: Mapped["Hearing"] = relationship(back_populates="community_submissions")


class HearingAttendance(Base):
    """A CUSG Justice's RSVP status for a specific hearing -- "this is my
    name and I will be attending/not attending/may be attending." Not in
    the original spec; added on request. One row per (hearing, justice) --
    setting it again updates the same row rather than creating a new one,
    so each justice always has exactly one current status per hearing."""
    __tablename__ = "hearing_attendance"
    __table_args__ = (
        UniqueConstraint("hearing_id", "justice_id", name="uq_attendance_hearing_justice"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    hearing_id: Mapped[str] = mapped_column(ForeignKey("hearings.id"), nullable=False, index=True)
    justice_id: Mapped[str] = mapped_column(ForeignKey("admin_users.id"), nullable=False, index=True)

    status: Mapped[AttendanceStatus] = mapped_column(Enum(AttendanceStatus), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    hearing: Mapped["Hearing"] = relationship(back_populates="attendance")
    justice: Mapped["AdminUser"] = relationship()


class HearingRecommendation(Base):
    """A Justice flagging a hearing for the rest of the court to check out,
    with a note on why -- "a special place for the rest of the justices to
    check out." Not in the original spec; added on request. Distinct from
    the Editor/Contributor curated_blurb (Section 5.2's public "why watch
    this" text): this is peer-to-peer, justice-to-justice, not a
    publicly-curated blurb."""
    __tablename__ = "hearing_recommendations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    hearing_id: Mapped[str] = mapped_column(ForeignKey("hearings.id"), nullable=False, index=True)
    justice_id: Mapped[str] = mapped_column(ForeignKey("admin_users.id"), nullable=False, index=True)

    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    hearing: Mapped["Hearing"] = relationship(back_populates="recommendations")
    justice: Mapped["AdminUser"] = relationship()


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    filter_type: Mapped[SubscriptionFilterType] = mapped_column(Enum(SubscriptionFilterType), nullable=False)
    filter_value: Mapped[str] = mapped_column(String(255), nullable=False)
    frequency: Mapped[SubscriptionFrequency] = mapped_column(Enum(SubscriptionFrequency), nullable=False)
    unsubscribe_token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AcademicCalendarPeriod(Base):
    __tablename__ = "academic_calendar_periods"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    start_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    end_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    type: Mapped[AcademicPeriodType] = mapped_column(Enum(AcademicPeriodType), nullable=False)


class AdminUser(Base):
    """One login covers both possible "hats" (Section 5.4's curation
    Editor/Contributor roles, and being a CUSG Supreme Court Justice with
    attendance/recommendation privileges) rather than forcing two separate
    accounts for the same real person -- the roster is tiny (7 justices,
    plus whichever curators overlap with them) and the two concerns are
    genuinely independent, so `role` and `is_justice` are separate fields,
    not one combined enum."""
    __tablename__ = "admin_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    # Curation role (Section 5.4). Nullable: a justice-only account (no
    # curation duties) has no role here.
    role: Mapped[Optional[AdminRole]] = mapped_column(Enum(AdminRole), nullable=True)
    is_justice: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Display identity for justices (e.g. "Chief Justice Dillon Rankin"),
    # shown on attendance/recommendation UI instead of an email address.
    display_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class ActivityLogEntry(Base):
    """Section 5.4: "Activity log so multiple students on the team can
    coordinate without duplicating work." Not in the Section 6 schema
    listing but required by Section 5.4 - added here rather than bolted on
    later."""
    __tablename__ = "activity_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    admin_user_email: Mapped[str] = mapped_column(String(320), nullable=False)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)  # "hearing", "news_mention", ...
    target_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class JobRun(Base):
    """Section 8: job reliability / failure alerting needs a record of each
    scheduled run to detect "failed" or "unexpectedly empty" pulls."""
    __tablename__ = "job_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    success: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    rows_seen: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rows_upserted: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

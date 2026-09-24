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
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.availability import parse_hearing_time


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
    # Colorado's own two appellate courts (added on request, Section 12
    # deliverable "expand the data"). Real oral-argument case discovery for
    # these comes from CourtListener (court ids "colo" and "coloctapp",
    # confirmed live -- see docs/DATA_SOURCE_FINDINGS.md), curated the same
    # way as the federal supplement: CourtListener has no scheduling/oral-
    # argument-date feed for either (has_oral_argument_scraper=False for
    # both, confirmed live), only real, indexed opinions -- actual argument
    # *dates* come from Colorado's own published PDF calendars
    # (coloradojudicial.gov/supreme-court/supreme-court-oral-arguments and
    # .../topic/77/court-appeals-oral-arguments), which a curator reads
    # directly, the same way the Suncor SCOTUS date was confirmed.
    colorado_supreme_court = "colorado_supreme_court"
    colorado_court_of_appeals = "colorado_court_of_appeals"
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
    # Phase-6 doc, Section 3/6: a medium-confidence name match -- a real
    # candidate hearing is pre-selected (NewsMention.hearing_id is set),
    # but it needs a Justice's one-click confirm/reject rather than being
    # auto-attached outright.
    suggested_pending_review = "suggested_pending_review"
    # Real evidence, not the doc's original guess, drove this one: pulling
    # production's actual review queue found it dominated by articles with
    # no case number, no extractable party name, AND no court-relevance
    # language at all (school board votes, weather, opinion columns) --
    # general-purpose news feeds aren't filtered to court content before
    # this pipeline sees them. Those get discarded outright instead of
    # silently inflating an already-unworkable queue; a real court story
    # missing extractable details still lands in unmatched_review, not here.
    discarded = "discarded"


class MatchConfidence(str, enum.Enum):
    high = "high"
    medium = "medium"
    low = "low"


class SubscriptionFilterType(str, enum.Enum):
    hearing_type_category = "hearing_type_category"
    case_number = "case_number"
    keyword = "keyword"
    # Added on request: notify on any new entry to the Justice
    # recommendation board (Section "CUSG Justice features"), rather than
    # filtering hearings directly. filter_value is unused/ignored for this
    # type (the frontend sends a placeholder) since there's nothing to
    # filter -- every new recommendation qualifies.
    new_recommendation = "new_recommendation"
    # Phase-6.2 doc, Section 6: filter_value is unused (same reasoning as
    # new_recommendation above) -- the real filter is availability_blocks.
    personal_availability = "personal_availability"


class SubscriptionFrequency(str, enum.Enum):
    weekly_digest = "weekly_digest"
    # Historically named for the "follow one case" use case; also now used
    # for new_recommendation subscriptions below, since both mean "email
    # immediately when the triggering event happens" rather than something
    # specific to case-following. Not renamed to avoid an unrelated schema
    # churn -- see docs/ARCHITECTURE.md.
    realtime_for_followed_case = "realtime_for_followed_case"


class AcademicPeriodType(str, enum.Enum):
    break_ = "break"
    finals = "finals"


class SubmissionStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class ProceedingStage(str, enum.Enum):
    """Phase-2 doc, Section 5: "distinct from the existing
    hearing_type_category, describing what was actually witnessed."
    Doc's own suggested list, used as-is (Section 9 open question #5
    flags this as confirmable/extensible -- `other` plus this being a
    plain string-backed enum, not something requiring a migration to add
    to, is the extensibility path)."""
    opening_statements = "opening_statements"
    closing_arguments = "closing_arguments"
    sentencing = "sentencing"
    oral_argument = "oral_argument"
    jury_selection = "jury_selection"
    motions_hearing = "motions_hearing"
    other = "other"


class ArchiveSubmitterRole(str, enum.Enum):
    justice = "justice"
    regular_user = "regular_user"


class ReportTargetType(str, enum.Enum):
    """Phase-4 doc, Section 2.5: the two kinds of unmoderated public
    content a "Report" link can flag -- an Archive entry (publishes
    immediately, no review) or a recommendation (also unmoderated free
    text)."""
    archive_entry = "archive_entry"
    recommendation = "recommendation"


class AdminRole(str, enum.Enum):
    editor = "editor"
    contributor = "contributor"


class AttendanceStatus(str, enum.Enum):
    attending = "attending"
    not_attending = "not_attending"
    maybe = "maybe"


class LivestreamSourceType(str, enum.Enum):
    """Phase-2 doc, Section 2. Colorado's own livestream portal
    (live.coloradojudicial.gov, confirmed live and reachable) covers the
    state courts (county/district and, per that same portal, Colorado's
    own Supreme Court/Court of Appeals); federal courts don't offer public
    video, only an occasional published audio-access line, entered
    per-case rather than assumed; SCOTUS has a real, standing live-audio
    page for oral arguments. See app/livestream.py for the default
    assignment and the honest availability caveats -- none of these
    guarantee an actual stream exists for a given hearing, since
    streaming state trials/evidentiary hearings is judge's-discretion
    under CJD 23-02, not presumptive."""
    state_portal = "state_portal"
    federal_audio_line = "federal_audio_line"
    scotus_audio = "scotus_audio"
    none = "none"


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

    # Phase-2 doc, Section 2: defaulted by court_location (see
    # app/livestream.py::default_livestream), overridable per-row (e.g. a
    # curator adds a specific federal audio-access line for one case).
    # Labeled honestly, not as a guarantee -- see LivestreamSourceType.
    livestream_source_type: Mapped[LivestreamSourceType] = mapped_column(
        Enum(LivestreamSourceType), nullable=False, default=LivestreamSourceType.none
    )
    livestream_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

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
        # Phase-6 doc: explicit allowlist, not "!= unmatched_review" --
        # that used to also count a merely-*suggested* match (not yet
        # confirmed by a Justice) or a discarded one as "in the news,"
        # which the new confidence-tiered statuses made actually wrong.
        confirmed = (MatchStatus.auto_matched, MatchStatus.manually_linked)
        return any(nm.match_status in confirmed for nm in self.news_mentions)

    @property
    def time_sort_key(self) -> int:
        """Minutes since midnight, for chronological sorting -- `time` is
        stored as whatever free-text string the source gave us (docket
        export or a curator typing "9:00 AM"), so `ORDER BY time` in SQL
        sorts it *alphabetically*, not chronologically. Real bug, caught
        against real live data: a day mixing "10:00 AM", "1:00 PM", and
        "9:00 AM" rendered in that exact wrong order, since '1' < '9' as
        the first character. Unparseable or missing times sort last.

        Delegates to app.availability.parse_hearing_time, the one shared
        home for this parsing logic (also used by the Phase-6.2 Justice
        availability meter and digest matching)."""
        parsed = parse_hearing_time(self.time)
        return parsed if parsed is not None else 24 * 60  # unparseable/blank -- after every real time, not before


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
    # Phase-6 doc, Section 6: null until a match attempt actually scored
    # something (a pure case-number match doesn't need a confidence tier
    # at all -- it's always high). match_signals is the diagnosis tool
    # Section 1 asked for: exactly which signals fired and their raw
    # values, not just the final tier -- see
    # app/jobs/news_matching.py::MatchEvaluation.signals for the shape.
    match_confidence: Mapped[Optional[MatchConfidence]] = mapped_column(Enum(MatchConfidence), nullable=True)
    match_signals: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON object
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    # Phase-6 doc, Section 5: retroactive re-matching needs to know which
    # rows are still worth re-attempting (unmatched_review/
    # suggested_pending_review, not auto_matched/manually_linked/
    # discarded) without re-scanning every row ever seen -- tracked
    # directly rather than inferred solely from match_status so a future
    # status value doesn't silently break the re-match query.
    last_match_attempt_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

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


class ArchiveEntry(Base):
    """Phase-2 doc, Section 5: a public, browsable record of hearings the
    team or public actually attended and wrote up -- separate from the
    live/upcoming calendar. Two submission paths converge here:
    - Regular (public, no login) users: "Submit a Summary" -- a display
      name, no password, the same lightweight pattern already used for
      email subscriptions. Publishes immediately, no approval queue (a
      deliberate choice -- see the after-the-fact safeguards below).
    - Justices (logged in): "Mark Attendance" on a hearing that's already
      happened, which is really just creating (or editing) this same kind
      of entry with attendees populated and submitted_by_role=justice --
      reflection_text is optional for this path (a Justice can record
      "I was there" without necessarily writing a narrative), required
      for the public "Submit a Summary" path (see ArchiveEntryIn).

    Removing the pre-publish approval queue for a fully anonymous input
    (unlike CommunitySubmission, which stays moderated) trades a
    pre-publish safety net for after-the-fact ones instead: `submitter_ip`
    is logged (never shown publicly) so abuse can be traced, and any
    Justice can edit or remove any entry after the fact -- see
    routers/archive.py.
    """
    __tablename__ = "archive_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    hearing_id: Mapped[str] = mapped_column(ForeignKey("hearings.id"), nullable=False, index=True)

    proceeding_stage: Mapped[ProceedingStage] = mapped_column(Enum(ProceedingStage), nullable=False, index=True)
    judge_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    # JSON-encoded list of attendee display names (Justices via attendance
    # marks, plus the submitter's own name for a regular-user summary).
    attendees: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reflection_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    submitted_by_name: Mapped[str] = mapped_column(String(120), nullable=False)
    submitted_by_role: Mapped[ArchiveSubmitterRole] = mapped_column(Enum(ArchiveSubmitterRole), nullable=False)
    # Phase-3 doc, Section 4: lets a Justice-submitted entry's byline link
    # to that Justice's public profile. Only ever set for the "Mark
    # Attendance" path (submitted_by_role == justice), where the real
    # AdminUser is known at write time -- not backfillable for entries
    # created before this column existed, which just render their byline
    # as plain text (honest degradation, not an error).
    submitted_by_justice_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("admin_users.id"), nullable=True
    )

    # Internal-only, never exposed via ArchiveEntryOut -- Section 6's
    # after-the-fact abuse-tracing safeguard for a fully anonymous,
    # unmoderated public input.
    submitter_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    hearing: Mapped["Hearing"] = relationship()


class ContentReport(Base):
    """Phase-4 doc, Section 2.5: a "Report" link on every public Archive
    entry and recommendation, since both publish with no pre-review.
    Doesn't remove or hide anything itself -- just notifies every
    Justice (Section 5.4's explicit choice over a single designated
    moderator, same audience as a new recommendation) and lands in the
    admin dashboard's Reports queue for a Justice to look at and act on
    by hand (edit/delete the Archive entry, delete the recommendation --
    the tools for both already exist)."""
    __tablename__ = "content_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    target_type: Mapped[ReportTargetType] = mapped_column(Enum(ReportTargetType), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Internal-only, never exposed via ReportOut -- same reasoning as
    # ArchiveEntry.submitter_ip.
    reporter_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


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
    # Phase-6.2 doc, Section 6: JSON-encoded list of {day_of_week,
    # start_time, end_time} blocks, only used when filter_type ==
    # personal_availability. Same shape/format as AdminUser.availability_blocks
    # below, and matched with the same app.availability.hearing_matches_blocks
    # function the Justice-only meter uses.
    availability_blocks: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class AcademicCalendarPeriod(Base):
    __tablename__ = "academic_calendar_periods"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    start_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    end_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    type: Mapped[AcademicPeriodType] = mapped_column(Enum(AcademicPeriodType), nullable=False)


class AdminUser(Base):
    """One login covers both possible "hats" (Section 5.4's curation
    Editor/Contributor roles, and being a CUSG Court Justice with
    attendance/recommendation privileges) rather than forcing two separate
    accounts for the same real person. `role` and `is_justice` stay
    separate *fields* -- is_justice is identity ("this account is one of
    the 7-8 real Justices," gating attendance/recommend/profile-editing),
    role is curation authority (gating the admin review-queue tool).

    Phase-3 doc, Section 2, explicit choice: **every Justice account also
    gets full curation access** -- reversing this build's earlier "keep
    them independent" stance (a justice-only account with no curation
    role was possible before; it no longer is, going forward).
    Implemented as a plain data fact rather than a code-level merge of
    require_justice/require_editor: provisioning a Justice (invite-accept
    in routers/account.py, and the one-time backfill in app/migrations.py
    for the original 7 seeded pre-Phase-3) sets `role=AdminRole.editor`
    directly. require_editor's own check (`role == editor`) never
    changed, so the real Editor-vs-Contributor distinction for curation
    work is untouched -- a Justice simply always *is* an Editor now, by
    construction, not by a special-cased permission check."""
    __tablename__ = "admin_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    # Curation role (Section 5.4). Nullable: a contributor-only or
    # not-yet-provisioned account has no role here. See class docstring --
    # every Justice account gets AdminRole.editor set here directly.
    role: Mapped[Optional[AdminRole]] = mapped_column(Enum(AdminRole), nullable=True)
    is_justice: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Display identity for justices (e.g. "Chief Justice Dillon Rankin"),
    # shown on attendance/recommendation UI instead of an email address.
    display_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    # --- Phase-3 doc, Section 3: public Justice profiles ---------------
    # All nullable/optional -- a brand-new Justice account has none of
    # this filled in yet, and the public directory/profile pages render
    # sensible blanks rather than requiring it up front.
    bio: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    year_or_major: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    why_care: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fun_fact: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Real photo upload (Section 6.3's explicit choice over an avatar
    # picker). Stored directly in Postgres rather than a separate file/
    # object-storage service -- this project has no such service
    # provisioned, and 7-8 people's profile photos (re-encoded and capped
    # to a small size on upload -- see routers/account.py) is a trivial
    # amount of data for a database column. Never exposed directly in any
    # *Out schema; served only via GET /api/justices/{id}/photo.
    photo_data: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    photo_content_type: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)

    # --- Phase-4 doc, Section 2.3: account lockout + 2FA ----------------
    # Reset to 0 on any successful login; a failed one increments it, and
    # hitting LOCKOUT_THRESHOLD (app/routers/admin.py) sets locked_until
    # and resets the counter -- belt-and-suspenders alongside the
    # existing per-IP login rate limit (that one stops one IP hammering
    # any account; this one stops a distributed attempt against one
    # specific account from many IPs).
    failed_login_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # TOTP secret is set (but totp_enabled left False) the moment setup
    # starts, and only takes effect at login once confirm_2fa verifies a
    # real code against it -- an abandoned setup just leaves an unused
    # secret sitting here, harmless since totp_enabled gates everything.
    totp_secret: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # JSON-encoded list of *hashed* one-time backup codes (same
    # sha256-via-hash_token treatment as invite/reset tokens -- these are
    # also high-entropy random strings, not human-chosen secrets).
    # Consuming one removes it from the list.
    totp_backup_code_hashes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # --- Phase-6.2 doc, Section 4: recurring weekly availability --------
    # JSON-encoded list of {day_of_week, start_time, end_time} blocks --
    # Justice-only, never exposed via JusticeOut (the schema shared by the
    # public roster/profile endpoints). See app/availability.py and the
    # dedicated /me/availability endpoints in routers/account.py.
    availability_blocks: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class AdminInvite(Base):
    """Phase-3 doc, Section 1: provisioning is invite-link, not open
    self-registration or a shared signup code -- an Editor enters a real
    Justice's name/email here, they get emailed a one-time expiring link
    to set their own password (routers/account.py). Re-inviting an email
    that already has an account (a reset, or fixing a typo) is allowed --
    accepting the new invite just updates that existing row rather than
    erroring on the unique email constraint.

    `token` is stored hashed (sha256 via app.auth.hash_token), same
    reasoning as password hashing: a database read (a backup, a bug, an
    over-broad log line) shouldn't hand out a working credential.
    """
    __tablename__ = "admin_invites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    created_by_email: Mapped[str] = mapped_column(String(320), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class PasswordResetToken(Base):
    """Phase-3 doc, Section 2: standard "forgot password" email-link flow.
    Single-use and expiring, same as AdminInvite, and for the same
    reason -- token stored hashed, never in plaintext."""
    __tablename__ = "password_reset_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    admin_user_id: Mapped[str] = mapped_column(ForeignKey("admin_users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    admin_user: Mapped["AdminUser"] = relationship()


class JusticeAllowlistEntry(Base):
    """Follow-up to Phase 3, Section 1: lets a known Justice self-serve
    their own invite link (POST /api/justices/request-invite) instead of
    needing an existing Editor/Justice to click "Create invite" on their
    behalf every time -- while keeping the doc's original "only 7-8 known
    people, never open self-registration" guarantee, since only an
    email already on this list can ever trigger a real invite send. An
    Editor still adds each real Justice's email here once (that's the
    actual gate, same trust boundary as before); self-service just
    replaces *who clicks the button* to actually send the link.

    Additive alongside the original direct-invite flow
    (POST /api/admin/invites), not a replacement of it -- an Editor can
    still invite someone directly without them needing to know this page
    exists at all."""
    __tablename__ = "justice_allowlist"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    added_by_email: Mapped[str] = mapped_column(String(320), nullable=False)
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

"""
Phase 3 (Section 5.3): weekly digest generation, plus per-case realtime
alerts. Section 5.5 requires suppressing/shortening the digest during CU
breaks and finals.

No transactional-email account exists for this build (Section 10 open
question left to the CUSG team to set up), so send_email() with
EMAIL_BACKEND="console" renders the digest and logs it rather than
delivering it -- the rendering/selection logic is fully real and testable,
only the last-mile delivery is stubbed. Swap in SendGrid/Postmark/etc.
behind send_email() when credentials exist.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.academic_calendar import current_period
from app.config import EMAIL_BACKEND
from app.models import (
    AcademicPeriodType,
    AppearanceType,
    CaseCategory,
    Hearing,
    HearingStatus,
    Subscription,
    SubscriptionFilterType,
    SubscriptionFrequency,
)

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str) -> None:
    if EMAIL_BACKEND == "console":
        logger.info("EMAIL to=%s subject=%r\n%s", to, subject, body)
        return
    raise NotImplementedError(f"Unknown EMAIL_BACKEND {EMAIL_BACKEND!r}")


def default_upcoming_hearings(db: Session, days_ahead: int = 14) -> list[Hearing]:
    today = date.today()
    return (
        db.query(Hearing)
        .filter(
            Hearing.date >= today,
            Hearing.date <= today + timedelta(days=days_ahead),
            Hearing.status != HearingStatus.cancelled,
            Hearing.is_excluded.is_(False),
            Hearing.case_category != CaseCategory.juvenile,
            Hearing.appearance_type == AppearanceType.in_person,
        )
        .order_by(Hearing.date, Hearing.time)
        .all()
    )


def hearings_matching_subscription(db: Session, sub: Subscription) -> list[Hearing]:
    hearings = default_upcoming_hearings(db)
    if sub.filter_type == SubscriptionFilterType.hearing_type_category:
        return [h for h in hearings if h.hearing_type_category.value == sub.filter_value]
    if sub.filter_type == SubscriptionFilterType.case_number:
        return [h for h in hearings if h.case_number.upper() == sub.filter_value.upper()]
    if sub.filter_type == SubscriptionFilterType.keyword:
        needle = sub.filter_value.lower()
        return [h for h in hearings if needle in (h.curated_blurb or "").lower()
                or needle in h.hearing_type_display.lower()]
    return []


def render_digest(hearings: list[Hearing], quiet_week: bool, period_label: str | None) -> str:
    if quiet_week:
        lines = [
            f"CU is on {period_label or 'break'} this week, so this digest is short.",
            "Court proceedings continue regardless -- here's what's on the docket if you're still around:",
            "",
        ]
        hearings = hearings[:5]
    else:
        lines = ["Upcoming Boulder-area hearings worth watching:", ""]

    if not hearings:
        lines.append("Nothing matching your filters this week.")
    for h in hearings:
        news_flag = " [IN THE NEWS]" if h.has_news_mention else ""
        lines.append(f"- {h.date} {h.time or ''} | {h.hearing_type_display}{news_flag}")
        lines.append(f"  Case {h.case_number} | {h.court_location.value} | Courtroom {h.courtroom or 'TBD'}")
        if h.curated_blurb:
            lines.append(f"  {h.curated_blurb}")
    lines.append("")
    lines.append("Confirm details on the official docket before attending -- hearings can move or be cancelled.")
    return "\n".join(lines)


@dataclass
class DigestSummary:
    subscriptions_processed: int
    quiet_week: bool


def run_weekly_digest(db: Session, today: date | None = None) -> DigestSummary:
    today = today or date.today()
    period = current_period(db, today)
    quiet_week = period is not None
    period_label = period.label if period else None

    subs = (
        db.query(Subscription)
        .filter(Subscription.is_active.is_(True),
                Subscription.frequency == SubscriptionFrequency.weekly_digest)
        .all()
    )

    for sub in subs:
        matching = hearings_matching_subscription(db, sub)
        subject = "CUSG Boulder Court Tracker: quiet week" if quiet_week else "CUSG Boulder Court Tracker: this week's hearings"
        body = render_digest(matching, quiet_week, period_label)
        body += f"\n\nUnsubscribe: /unsubscribe/{sub.unsubscribe_token}"
        send_email(sub.email, subject, body)

    return DigestSummary(subscriptions_processed=len(subs), quiet_week=quiet_week)


def notify_realtime_subscribers_of_change(db: Session, hearing: Hearing) -> int:
    """Section 5.3: immediate alert when a followed case's hearing changes
    or is cancelled. Called by the docket-pull job's caller after a run
    finds status=changed/cancelled rows for a case someone follows."""
    subs = (
        db.query(Subscription)
        .filter(
            Subscription.is_active.is_(True),
            Subscription.frequency == SubscriptionFrequency.realtime_for_followed_case,
            Subscription.filter_type == SubscriptionFilterType.case_number,
            Subscription.filter_value.ilike(hearing.case_number),
        )
        .all()
    )
    for sub in subs:
        subject = f"Update on case {hearing.case_number}"
        body = (
            f"Status: {hearing.status.value}\n"
            f"{hearing.change_note or ''}\n\n"
            f"{hearing.date} {hearing.time or ''} | {hearing.hearing_type_display}\n"
            f"Unsubscribe: /unsubscribe/{sub.unsubscribe_token}"
        )
        send_email(sub.email, subject, body)
    return len(subs)


def notify_subscribers_of_new_recommendation(db: Session, recommendation) -> int:
    """Added on request: email anyone subscribed to new_recommendation the
    moment a Justice adds one to the board. Called from
    routers/justices.py::create_recommendation() right after the row is
    committed."""
    subs = (
        db.query(Subscription)
        .filter(
            Subscription.is_active.is_(True),
            Subscription.filter_type == SubscriptionFilterType.new_recommendation,
            Subscription.frequency == SubscriptionFrequency.realtime_for_followed_case,
        )
        .all()
    )
    hearing = recommendation.hearing
    justice_name = recommendation.justice.display_name or recommendation.justice.email
    for sub in subs:
        subject = "New court recommendation"
        body = (
            f"{justice_name} recommended a hearing to watch:\n\n"
            f"{hearing.hearing_type_display}\n"
            f"Case {hearing.case_number} | {hearing.date} {hearing.time or ''}\n"
            f"{recommendation.note or ''}\n\n"
            f"See it at /recommendations\n"
            f"Unsubscribe: /unsubscribe/{sub.unsubscribe_token}"
        )
        send_email(sub.email, subject, body)
    return len(subs)

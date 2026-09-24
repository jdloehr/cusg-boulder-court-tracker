"""
Phase 3 (Section 5.3): weekly digest generation, plus per-case realtime
alerts. Section 5.5 requires suppressing/shortening the digest during CU
breaks and finals.

send_email() defaults to EMAIL_BACKEND="console" (renders and logs the
email rather than delivering it -- the rendering/selection logic here is
fully real and testable regardless of whether delivery is). Set
EMAIL_BACKEND=sendgrid (plus SENDGRID_API_KEY/EMAIL_FROM_ADDRESS in
app/config.py) for real delivery via SendGrid's plain HTTP API -- see
docs/DEPLOYMENT.md's "Real email delivery" section for how to get an
account and API key. Deliberately a raw httpx.post() call rather than
SendGrid's own SDK: one API call doesn't need a whole extra dependency
when this project already depends on httpx for everything else.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

import json

import httpx
from sqlalchemy.orm import Session

from app.academic_calendar import current_period
from app.availability import hearing_matches_blocks
from app.config import EMAIL_BACKEND, EMAIL_FROM_ADDRESS, EMAIL_FROM_NAME, SENDGRID_API_KEY
from app.models import (
    AcademicPeriodType,
    AdminUser,
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
    if EMAIL_BACKEND == "sendgrid":
        _send_via_sendgrid(to, subject, body)
        return
    raise NotImplementedError(f"Unknown EMAIL_BACKEND {EMAIL_BACKEND!r}")


def _send_via_sendgrid(to: str, subject: str, body: str) -> None:
    """Never raises -- a failed send (bad API key, an unverified sender,
    SendGrid being briefly down) shouldn't crash the request that
    triggered it. The digest job already tolerates per-recipient failures
    (Section 8's failure-alerting is separate from this), and an invite/
    reset email failing is recoverable anyway -- the invite link is also
    returned directly in the API response (see routers/account.py), and
    an Editor can just re-send. Failures are logged loudly instead."""
    if not SENDGRID_API_KEY or not EMAIL_FROM_ADDRESS:
        logger.error(
            "EMAIL_BACKEND=sendgrid but SENDGRID_API_KEY/EMAIL_FROM_ADDRESS aren't both set -- "
            "email to=%s subject=%r was NOT sent", to, subject,
        )
        return
    try:
        resp = httpx.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={"Authorization": f"Bearer {SENDGRID_API_KEY}"},
            json={
                "personalizations": [{"to": [{"email": to}]}],
                "from": {"email": EMAIL_FROM_ADDRESS, "name": EMAIL_FROM_NAME},
                "subject": subject,
                "content": [{"type": "text/plain", "value": body}],
            },
            timeout=10,
        )
        if resp.status_code >= 400:
            logger.error("SendGrid send to=%s failed (%s): %s", to, resp.status_code, resp.text)
    except httpx.HTTPError as exc:
        logger.error("SendGrid send to=%s raised %s: %s", to, type(exc).__name__, exc)


def default_upcoming_hearings(db: Session, days_ahead: int = 14) -> list[Hearing]:
    today = date.today()
    hearings = (
        db.query(Hearing)
        .filter(
            Hearing.date >= today,
            Hearing.date <= today + timedelta(days=days_ahead),
            Hearing.status != HearingStatus.cancelled,
            Hearing.is_excluded.is_(False),
            Hearing.case_category != CaseCategory.juvenile,
            Hearing.appearance_type == AppearanceType.in_person,
        )
        .order_by(Hearing.date)
        .all()
    )
    # Sorted in Python: see Hearing.time_sort_key's docstring for why
    # ORDER BY on the free-text `time` column doesn't sort chronologically.
    return sorted(hearings, key=lambda h: (h.date, h.time_sort_key))


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
    if sub.filter_type == SubscriptionFilterType.personal_availability:
        # Phase-6.2 doc, Section 6: same overlap function the Justice-only
        # availability meter uses (app/availability.py), so the digest and
        # the meter can never disagree with each other.
        blocks = json.loads(sub.availability_blocks) if sub.availability_blocks else []
        return [h for h in hearings if hearing_matches_blocks(h.date, h.time, h.duration, blocks)]
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


def notify_all_justices_of_new_recommendation(db: Session, recommendation) -> int:
    """Phase-2 doc, Section 4: "An automatic email is sent to all Justices"
    -- distinct from notify_subscribers_of_new_recommendation() above,
    which serves the public /subscribe feature (any email, no login).
    Every active Justice gets this one automatically, with no
    subscription step, since it's their own court's recommendation."""
    justices = db.query(AdminUser).filter(AdminUser.is_justice.is_(True), AdminUser.is_active.is_(True)).all()
    hearing = recommendation.hearing
    justice_name = recommendation.justice.display_name or recommendation.justice.email
    for j in justices:
        subject = f"{justice_name} recommends a hearing"
        body = (
            f"{justice_name} recommended a hearing to the court:\n\n"
            f"{hearing.hearing_type_display}\n"
            f"Case {hearing.case_number} | {hearing.date} {hearing.time or ''}\n\n"
            f"Reason: {recommendation.note}\n\n"
            f"See it at /hearings/{hearing.id}"
        )
        send_email(j.email, subject, body)
    return len(justices)


def notify_all_justices_of_report(db: Session, target_type: str, target_id: str,
                                   reason: str | None, admin_url: str) -> int:
    """Phase-4 doc, Section 2.5/5.4: a "Report" flag on an Archive entry
    or recommendation notifies every Justice (the explicit choice over a
    single designated moderator) rather than routing to one person --
    same reasoning/audience as notify_all_justices_of_new_recommendation
    above."""
    justices = db.query(AdminUser).filter(AdminUser.is_justice.is_(True), AdminUser.is_active.is_(True)).all()
    for j in justices:
        subject = f"Content reported: {target_type.replace('_', ' ')}"
        body = (
            f"Someone reported a {target_type.replace('_', ' ')} (id {target_id}).\n\n"
            f"Reason given: {reason or '(none provided)'}\n\n"
            f"Review it in the dashboard's Reports queue: {admin_url}"
        )
        send_email(j.email, subject, body)
    return len(justices)

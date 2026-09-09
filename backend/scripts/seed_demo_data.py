#!/usr/bin/env python3
"""
One-shot script that exercises the whole pipeline against REAL data and
leaves a populated local database for the frontend demo:

1. Runs the real docket-pull job against live coloradojudicial.gov data.
2. Runs the real news-monitoring job against live RSS feeds.
3. Adds the real CU Boulder Fall 2026 academic-calendar periods (Fall
   Break + Finals Week, from the registrar's published dates).
4. Creates two demo admin accounts (one editor, one contributor).
5. Publishes ONE real federal case as a curated Section 2.3 supplement
   entry: Suncor Energy (U.S.A.) Inc. v. County Commissioners of Boulder
   County, No. 25-170 -- confirmed directly against supremecourt.gov during
   build, oral argument scheduled Monday, October 5, 2026. This is real
   data, not a fixture -- see docs/DATA_SOURCE_FINDINGS.md section 5.
6. Publishes a curated blurb on one real upcoming jury trial, as an example
   of what the curation team's job looks like day to day.
7. Adds one demo email subscription.

Safe to re-run -- everything here is either idempotent (docket pull, news
monitor, academic calendar periods created only if missing) or guarded
against duplicate creation (admin users, the federal case, the subscription).
"""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth import hash_password  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.hearing_types import classify_hearing_type  # noqa: E402
from app.jobs.docket_pull import run_docket_pull  # noqa: E402
from app.jobs.news_monitor import run_news_monitor  # noqa: E402
from app.models import (  # noqa: E402
    AcademicCalendarPeriod,
    AcademicPeriodType,
    AdminRole,
    AdminUser,
    ActivityLogEntry,
    AppearanceType,
    CaseCategory,
    CourtLocation,
    Hearing,
    HearingSource,
    HearingStatus,
    HearingTypeCategory,
    Subscription,
    SubscriptionFilterType,
    SubscriptionFrequency,
)


def seed_academic_calendar(db):
    periods = [
        ("Fall Break 2026", date(2026, 11, 23), date(2026, 11, 27), AcademicPeriodType.break_),
        ("Finals Week Fall 2026", date(2026, 12, 7), date(2026, 12, 11), AcademicPeriodType.finals),
    ]
    for label, start, end, ptype in periods:
        exists = db.query(AcademicCalendarPeriod).filter(AcademicCalendarPeriod.label == label).first()
        if exists:
            continue
        db.add(AcademicCalendarPeriod(label=label, start_date=start, end_date=end, type=ptype))
        print(f"Added academic calendar period: {label} ({start}..{end})")
    db.commit()


def seed_admin_users(db):
    demo_users = [
        ("editor@cusg-demo.colorado.edu", AdminRole.editor),
        ("contributor@cusg-demo.colorado.edu", AdminRole.contributor),
    ]
    for email, role in demo_users:
        if db.query(AdminUser).filter(AdminUser.email == email).first():
            continue
        db.add(AdminUser(email=email, hashed_password=hash_password("changeme"), role=role))
        print(f"Created demo {role.value} account: {email} / changeme")
    db.commit()


def seed_federal_supplement(db):
    """Real case, confirmed against supremecourt.gov during build (see
    docs/DATA_SOURCE_FINDINGS.md section 5) -- not a synthetic fixture."""
    case_number = "SCOTUS-25-170"
    if db.query(Hearing).filter(Hearing.case_number == case_number).first():
        print("Federal supplement case already seeded, skipping.")
        return

    type_result = classify_hearing_type("Oral Argument")
    hearing = Hearing(
        source=HearingSource.federal_courtlistener,
        case_number=case_number,
        case_category=CaseCategory.civil,
        party_names=json.dumps(["Suncor Energy (U.S.A.) Inc.", "County Commissioners of Boulder County"]),
        hearing_type_raw="Oral Argument",
        hearing_type_display=type_result.display,
        hearing_type_category=type_result.category.value,
        date=date(2026, 10, 5),
        time="10:00 AM",
        court_location=CourtLocation.us_supreme_court,
        courtroom="U.S. Supreme Court, Washington, D.C. -- also livestreamed",
        appearance_type=AppearanceType.in_person,
        status=HearingStatus.scheduled,
        curated_blurb=(
            "Suncor Energy (U.S.A.) Inc., et al. v. County Commissioners of Boulder County, et al., "
            "No. 25-170. Boulder County sued Suncor and Exxon in 2018 seeking damages for climate "
            "change impacts; the case's path through the Colorado state courts (Tenth Circuit, then "
            "the Colorado Supreme Court) is documented on CourtListener. The U.S. Supreme Court "
            "granted certiorari on the question of whether federal law preempts these state-law "
            "climate damages claims -- a major test case other Colorado-originated climate suits are "
            "watching. Not a Boulder courtroom, but Boulder County is literally the named party; "
            "in-person seating at the Court is extremely limited, but the argument is livestreamed."
        ),
    )
    db.add(hearing)
    db.add(ActivityLogEntry(
        admin_user_email="editor@cusg-demo.colorado.edu",
        action="published_federal_candidate",
        target_type="hearing",
        target_id=None,
        detail="Suncor Energy v. County Commissioners of Boulder County (SCOTUS 25-170)",
    ))
    db.commit()
    print("Seeded real federal supplement case: Suncor v. Boulder County (SCOTUS 25-170), "
          "oral argument 2026-10-05")


def seed_curated_blurb(db):
    """Pick a real upcoming jury trial from the live-pulled data and add an
    example curated blurb, demonstrating the Section 5.2 "why watch this"
    field against a real hearing (not a fixture)."""
    candidate = (
        db.query(Hearing)
        .filter(
            Hearing.hearing_type_category == HearingTypeCategory.jury_trial,
            Hearing.appearance_type == AppearanceType.in_person,
            Hearing.is_excluded.is_(False),
            Hearing.curated_blurb.is_(None),
        )
        .order_by(Hearing.date)
        .first()
    )
    if not candidate:
        print("No un-curated jury trial found to seed a blurb on (run docket pull first).")
        return

    blurb = (
        f"A {candidate.case_category.value} jury trial -- one of the more substantial proceedings "
        f"on the docket this window. Good pick if you want to see full trial procedure (jury "
        f"selection, opening statements, witness examination) rather than a brief procedural hearing. "
        f"Case {candidate.case_number}, Courtroom {candidate.courtroom or 'TBD'}. As always, call the "
        f"clerk's office or check the official docket the morning of, in case of a last-minute plea "
        f"deal or continuance."
    )
    candidate.curated_blurb_draft = blurb
    candidate.curated_blurb = blurb
    db.add(ActivityLogEntry(
        admin_user_email="editor@cusg-demo.colorado.edu",
        action="published_blurb",
        target_type="hearing",
        target_id=candidate.id,
        detail=f"Demo blurb on {candidate.case_number}",
    ))
    db.commit()
    print(f"Added a curated blurb to real hearing {candidate.case_number} ({candidate.date})")


def seed_subscription(db):
    email = "demo-subscriber@example.com"
    if db.query(Subscription).filter(Subscription.email == email).first():
        return
    db.add(Subscription(
        email=email,
        filter_type=SubscriptionFilterType.hearing_type_category,
        filter_value=HearingTypeCategory.jury_trial.value,
        frequency=SubscriptionFrequency.weekly_digest,
    ))
    db.commit()
    print(f"Added demo subscription for {email}")


def main():
    init_db()
    db = SessionLocal()
    try:
        print("=== 1/6 Real docket pull (coloradojudicial.gov) ===")
        job = run_docket_pull(db)
        print(f"  success={job.success} rows_seen={job.rows_seen} rows_upserted={job.rows_upserted}")

        print("\n=== 2/6 Real news monitor (RSS feeds) ===")
        job = run_news_monitor(db)
        print(f"  success={job.success} articles_seen={job.rows_seen} error={job.error_message}")

        print("\n=== 3/6 Academic calendar (real CU Boulder Fall 2026 dates) ===")
        seed_academic_calendar(db)

        print("\n=== 4/6 Demo admin accounts ===")
        seed_admin_users(db)

        print("\n=== 5/6 Federal supplement (real SCOTUS case) ===")
        seed_federal_supplement(db)

        print("\n=== 6/6 Curated blurb + demo subscription ===")
        seed_curated_blurb(db)
        seed_subscription(db)

        print("\nDone. Start the API with: uvicorn app.main:app --reload")
    finally:
        db.close()


if __name__ == "__main__":
    main()

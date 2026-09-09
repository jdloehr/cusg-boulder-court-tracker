"""
Section 5.5: academic-calendar awareness. AcademicCalendarPeriod rows are
maintained by an Editor (Section 5.4) a few times a year -- this module just
answers "is `day` inside a break/finals period?" for the banner (Section
5.1) and the digest-suppression logic (app/jobs/digest.py).
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models import AcademicCalendarPeriod


def current_period(db: Session, day: date | None = None) -> AcademicCalendarPeriod | None:
    day = day or date.today()
    return (
        db.query(AcademicCalendarPeriod)
        .filter(AcademicCalendarPeriod.start_date <= day, AcademicCalendarPeriod.end_date >= day)
        .first()
    )

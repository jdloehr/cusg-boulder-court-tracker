"""
Real bug, caught against real live production data (three real Colorado
Supreme Court oral arguments on one real day, September 22, 2026): `time`
is stored as whatever free-text string the source gives us ("9:00 AM",
"10:30 AM", "1:00 PM"), and `ORDER BY` on that column in SQL sorts it
*alphabetically*. "10:00 AM" sorts before "9:00 AM" because '1' < '9' as
the first character -- a real day on the live site rendered as
10:00 AM / 1:00 PM / 9:00 AM instead of 9:00 AM / 10:00 AM / 1:00 PM.
Fixed with Hearing.time_sort_key (parses to minutes-since-midnight) and
sorting in Python at both call sites (routers/public.py, jobs/digest.py)
instead of relying on SQL ORDER BY for this column.
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import (
    AppearanceType,
    Base,
    CaseCategory,
    CourtLocation,
    Hearing,
    HearingSource,
    HearingStatus,
    HearingTypeCategory,
)


@pytest.fixture()
def client_factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    db = TestSession()
    yield TestClient(app), db
    db.close()
    app.dependency_overrides.clear()


def _hearing(time, case_number="2026CR001"):
    return Hearing(
        source=HearingSource.state_docket_export,
        case_number=case_number,
        case_category=CaseCategory.criminal,
        hearing_type_raw="Jury Trial",
        hearing_type_display="Jury Trial",
        hearing_type_category=HearingTypeCategory.jury_trial.value,
        date=date(2026, 9, 22),
        time=time,
        court_location=CourtLocation.boulder_county,
        appearance_type=AppearanceType.in_person,
        status=HearingStatus.scheduled,
    )


def test_time_sort_key_orders_the_real_reported_case_correctly():
    # The exact real times from the September 22, 2026 Colorado Supreme
    # Court docket that exposed this bug live.
    times = ["10:00 AM", "1:00 PM", "9:00 AM"]
    hearings = [_hearing(t) for t in times]
    ordered = sorted(hearings, key=lambda h: h.time_sort_key)
    assert [h.time for h in ordered] == ["9:00 AM", "10:00 AM", "1:00 PM"]


def test_time_sort_key_handles_noon_and_midnight_boundaries():
    times = ["12:00 PM", "12:01 AM", "11:59 PM", "12:01 PM"]
    hearings = [_hearing(t) for t in times]
    ordered = sorted(hearings, key=lambda h: h.time_sort_key)
    assert [h.time for h in ordered] == ["12:01 AM", "12:00 PM", "12:01 PM", "11:59 PM"]


def test_time_sort_key_blank_or_unparseable_sorts_last():
    hearings = [_hearing("9:00 AM"), _hearing(None), _hearing("not a time"), _hearing("1:00 PM")]
    ordered = sorted(hearings, key=lambda h: h.time_sort_key)
    assert [h.time for h in ordered] == ["9:00 AM", "1:00 PM", None, "not a time"]


def test_api_returns_same_day_hearings_in_chronological_order(client_factory):
    """Full-stack check: GET /api/hearings on a day with the exact
    real problem times returns them in the right order, not DB order."""
    client, db = client_factory
    for t in ["10:00 AM", "1:00 PM", "9:00 AM"]:
        db.add(_hearing(t, case_number=f"2026CR00{t[:2].strip(':')}"))
    db.commit()

    resp = client.get("/api/hearings", params={"date_to": "2026-10-01", "show_all_types": "true"})
    assert resp.status_code == 200
    times = [h["time"] for h in resp.json()]
    assert times == ["9:00 AM", "10:00 AM", "1:00 PM"]

"""
GET /api/hearings/{id}/ics -- the per-hearing "Add to calendar" export.

Real bug caught manually (full-functionality pass, Phase 12+): this
endpoint computed `time_str` from the hearing's real start time and then
never used it anywhere -- every exported event came out as an all-day
VALUE=DATE block with no time at all, even though the docket export
almost always gives a real time string ("10:00 AM", etc.). Fixed to
convert the Mountain-time wall-clock value to a real UTC instant (same
ZoneInfo pattern as app/jobs/google_calendar_sync.py) and to use the
short `hearing_type_raw` instead of the long plain-language
`hearing_type_display` paragraph as the event's SUMMARY/title.
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


def _hearing(**overrides):
    defaults = dict(
        source=HearingSource.state_docket_export,
        case_number="2026CR001",
        case_category=CaseCategory.criminal,
        hearing_type_raw="Hearing on Advisement",
        hearing_type_display=(
            "Hearing on Advisement: the judge advises a defendant of their "
            "rights and the charges against them. Brief and procedural."
        ),
        hearing_type_category=HearingTypeCategory.other.value,
        date=date(2026, 10, 5),
        time="10:00 AM",
        duration="1 Hour(s)",
        courtroom="Courtroom F",
        court_location=CourtLocation.boulder_county,
        appearance_type=AppearanceType.in_person,
        status=HearingStatus.scheduled,
    )
    defaults.update(overrides)
    return Hearing(**defaults)


def test_ics_uses_the_real_hearing_time_not_an_all_day_event(client_factory):
    client, db = client_factory
    h = _hearing()
    db.add(h)
    db.commit()

    resp = client.get(f"/api/hearings/{h.id}/ics")
    assert resp.status_code == 200
    body = resp.text

    # 10:00 AM Mountain (MDT, UTC-6) in early October == 16:00 UTC.
    assert "DTSTART:20261005T160000Z" in body
    assert "DTEND:20261005T170000Z" in body
    assert "VALUE=DATE" not in body


def test_ics_summary_uses_the_short_raw_type_not_the_long_display_text(client_factory):
    client, db = client_factory
    h = _hearing()
    db.add(h)
    db.commit()

    body = client.get(f"/api/hearings/{h.id}/ics").text
    assert "SUMMARY:Hearing on Advisement - 2026CR001" in body
    # The long plain-language paragraph still belongs in DESCRIPTION, just
    # not duplicated into SUMMARY as an unwieldy calendar-event title.
    assert "SUMMARY:Hearing on Advisement: the judge advises" not in body
    assert "DESCRIPTION:Hearing on Advisement: the judge advises" in body


def test_ics_falls_back_to_all_day_when_time_is_unparseable(client_factory):
    client, db = client_factory
    h = _hearing(time="TBD")
    db.add(h)
    db.commit()

    body = client.get(f"/api/hearings/{h.id}/ics").text
    assert "DTSTART;VALUE=DATE:20261005" in body
    assert "DTEND" not in body


def test_ics_default_duration_used_when_duration_is_blank(client_factory):
    client, db = client_factory
    h = _hearing(duration=None)
    db.add(h)
    db.commit()

    body = client.get(f"/api/hearings/{h.id}/ics").text
    assert "DTSTART:20261005T160000Z" in body
    assert "DTEND:20261005T170000Z" in body  # DEFAULT_HEARING_DURATION_MINUTES == 60


def test_ics_404s_for_unknown_hearing(client_factory):
    client, _db = client_factory
    resp = client.get("/api/hearings/does-not-exist/ics")
    assert resp.status_code == 404

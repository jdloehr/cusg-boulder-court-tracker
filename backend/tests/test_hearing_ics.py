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


# --- RFC 5545 compliance (Oct 2026 review item 11) --------------------------

def test_ics_uses_crlf_line_endings_throughout(client_factory):
    """RFC 5545 requires CRLF, not a bare LF -- at least one real
    calendar client (reported during the review) silently dropped or
    mis-rendered events from a bare-LF .ics file."""
    client, db = client_factory
    h = _hearing()
    db.add(h)
    db.commit()

    body = client.get(f"/api/hearings/{h.id}/ics").text
    assert "\r\n" in body
    assert "\n" not in body.replace("\r\n", "")  # no bare LF left once every CRLF is accounted for
    assert body.startswith("BEGIN:VCALENDAR\r\n")
    assert body.endswith("END:VCALENDAR\r\n")


def test_ics_escapes_commas_semicolons_and_backslashes_in_text_fields(client_factory):
    """RFC 5545 section 3.3.11 -- a courtroom or case-number value
    ultimately comes from the docket export's own free text, not
    something this app controls, so this isn't purely theoretical."""
    client, db = client_factory
    h = _hearing(courtroom='F; Dept 3, "Annex"\\Building')
    db.add(h)
    db.commit()

    body = client.get(f"/api/hearings/{h.id}/ics").text
    location_line = next(line for line in body.split("\r\n") if line.startswith("LOCATION:"))
    assert location_line == r'LOCATION:boulder_county courtroom F\; Dept 3\, "Annex"\\Building'


def test_ics_escapes_a_literal_newline_in_text_fields_as_backslash_n(client_factory):
    """A literal line break inside a TEXT value must become the two
    characters "\\n", never an actual CRLF -- an unescaped one would
    split one property into two malformed lines."""
    client, db = client_factory
    h = _hearing(courtroom="F\nSecond floor")
    db.add(h)
    db.commit()

    body = client.get(f"/api/hearings/{h.id}/ics").text
    location_line = next(line for line in body.split("\r\n") if line.startswith("LOCATION:"))
    assert location_line == "LOCATION:boulder_county courtroom F\\nSecond floor"


def test_ics_escape_helper_escapes_backslashes_before_the_escapes_it_introduces():
    """Order matters: a literal backslash in the input must not get
    double-escaped by the ;/,/\\n handling applied afterward."""
    from app.routers.public import _ics_escape_text
    assert _ics_escape_text("a\\b;c,d") == r"a\\b\;c\,d"

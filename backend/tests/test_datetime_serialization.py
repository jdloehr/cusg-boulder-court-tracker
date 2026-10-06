"""
Oct 2026 review, Phase 2 item 1: every datetime field in app/schemas.py
is serialized as naive-but-really-UTC (datetime.utcnow() throughout this
codebase), and Pydantic's default serializer put no timezone suffix on
it at all. A browser's `new Date("2026-10-05T14:30:00")` parses a
timezone-less ISO string as *local* time (per the ECMA-262 Date Time
String Format spec), not UTC -- 6-7 hours off for anyone not in UTC
themselves. Fixed once via app.schemas.UTCDatetime, a shared Annotated
type every datetime *output* field now uses.
"""
from datetime import datetime, timezone

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
    JobRun,
)
from app.rate_limit import reset_for_tests
from app.schemas import DataStatusOut, _serialize_utc_datetime


def test_serialize_utc_datetime_adds_a_z_suffix_to_a_naive_value():
    assert _serialize_utc_datetime(datetime(2026, 10, 5, 14, 30, 0)) == "2026-10-05T14:30:00Z"


def test_serialize_utc_datetime_converts_an_already_aware_non_utc_value():
    from datetime import timedelta
    mdt = timezone(timedelta(hours=-6))
    local = datetime(2026, 10, 5, 8, 30, 0, tzinfo=mdt)  # 8:30 AM MDT == 2:30 PM UTC
    assert _serialize_utc_datetime(local) == "2026-10-05T14:30:00Z"


def test_data_status_out_json_has_a_z_suffix_not_a_bare_timestamp():
    d = DataStatusOut(
        last_updated_at=datetime(2026, 10, 5, 14, 30, 0), next_refresh_available_at=None,
        refresh_cooldown_minutes=20,
    )
    assert '"last_updated_at":"2026-10-05T14:30:00Z"' in d.model_dump_json()
    # Plain Python access (model_dump(), direct attribute access, a test
    # comparing two datetimes) is completely unaffected -- only the JSON
    # actually sent over the wire changes.
    assert d.last_updated_at == datetime(2026, 10, 5, 14, 30, 0)
    assert d.model_dump()["last_updated_at"] == datetime(2026, 10, 5, 14, 30, 0)


@pytest.fixture()
def client_factory():
    reset_for_tests()
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


def test_data_status_endpoint_returns_a_z_suffixed_timestamp(client_factory):
    client, db = client_factory
    db.add(JobRun(
        job_name="docket_pull", started_at=datetime(2026, 10, 5, 14, 30, 0),
        finished_at=datetime(2026, 10, 5, 14, 31, 0), success=True, rows_seen=0, rows_upserted=0,
    ))
    db.commit()

    body = client.get("/api/data-status").json()
    assert body["last_updated_at"] == "2026-10-05T14:31:00Z"  # data_status uses finished_at, not started_at


def test_hearing_detail_last_verified_at_is_z_suffixed(client_factory):
    client, db = client_factory
    h = Hearing(
        source=HearingSource.state_docket_export, case_number="2026CR001",
        case_category=CaseCategory.criminal, hearing_type_raw="Jury Trial", hearing_type_display="Jury Trial",
        hearing_type_category=HearingTypeCategory.jury_trial.value, date=datetime(2026, 10, 5).date(),
        time="9:00 AM", court_location=CourtLocation.boulder_county, appearance_type=AppearanceType.in_person,
        status=HearingStatus.scheduled, first_seen_at=datetime(2026, 10, 1, 7, 0, 0),
        last_verified_at=datetime(2026, 10, 4, 13, 15, 0),
    )
    db.add(h)
    db.commit()

    body = client.get(f"/api/hearings/{h.id}").json()
    assert body["last_verified_at"] == "2026-10-04T13:15:00Z"
    assert body["first_seen_at"] == "2026-10-01T07:00:00Z"

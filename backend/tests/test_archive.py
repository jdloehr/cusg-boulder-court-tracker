"""
Phase-2 doc, Section 5: Archive & Reflections. Full-stack TestClient tests,
same isolated in-memory-DB pattern as test_justices.py.
"""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.db import get_db
from app.main import app
from app.models import (
    AdminUser,
    AppearanceType,
    Base,
    CaseCategory,
    CourtLocation,
    Hearing,
    HearingSource,
    HearingStatus,
    HearingTypeCategory,
)
from app.rate_limit import reset_for_tests


@pytest.fixture()
def client():
    reset_for_tests()  # each test gets a fresh per-IP rate-limit budget
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

    seed = TestSession()
    past_hearing = Hearing(
        id="past-hearing",
        source=HearingSource.state_docket_export,
        case_number="2026CR000123",
        case_category=CaseCategory.criminal,
        hearing_type_raw="Jury Trial",
        hearing_type_display="Jury Trial",
        hearing_type_category=HearingTypeCategory.jury_trial.value,
        date=date.today() - timedelta(days=3),
        court_location=CourtLocation.boulder_county,
        appearance_type=AppearanceType.in_person,
        status=HearingStatus.scheduled,
    )
    future_hearing = Hearing(
        id="future-hearing",
        source=HearingSource.state_docket_export,
        case_number="2026CR000456",
        case_category=CaseCategory.civil,
        hearing_type_raw="Oral Argument",
        hearing_type_display="Oral Argument",
        hearing_type_category=HearingTypeCategory.oral_argument_motions.value,
        date=date.today() + timedelta(days=3),
        court_location=CourtLocation.boulder_county,
        appearance_type=AppearanceType.in_person,
        status=HearingStatus.scheduled,
    )
    joshua = AdminUser(email="joshua@test.local", hashed_password=hash_password("pw"),
                        is_justice=True, display_name="Joshua Loehr", title="Associate Justice")
    seed.add_all([past_hearing, future_hearing, joshua])
    seed.commit()
    seed.close()

    yield TestClient(app)
    app.dependency_overrides.clear()


def _auth(client, email="joshua@test.local"):
    token = client.post("/api/admin/login", json={"email": email, "password": "pw"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_public_can_submit_a_summary_no_login(client):
    r = client.post("/api/archive", json={
        "hearing_id": "past-hearing", "proceeding_stage": "closing_arguments",
        "reflection_text": "A genuinely thoughtful reflection on the closing arguments observed today.",
        "submitted_by_name": "A. Student",
    })
    assert r.status_code == 201
    body = r.json()
    assert body["submitted_by_role"] == "regular_user"
    assert body["submitted_by_name"] == "A. Student"


def test_public_submission_requires_a_reflection(client):
    r = client.post("/api/archive", json={
        "hearing_id": "past-hearing", "proceeding_stage": "sentencing",
        "submitted_by_name": "A. Student",
    })
    assert r.status_code == 400


def test_cannot_submit_for_a_hearing_that_hasnt_happened_yet(client):
    r = client.post("/api/archive", json={
        "hearing_id": "future-hearing", "proceeding_stage": "oral_argument",
        "reflection_text": "Preemptive write-up.", "submitted_by_name": "A. Student",
    })
    assert r.status_code == 400


def test_honeypot_silently_no_ops(client):
    r = client.post("/api/archive", json={
        "hearing_id": "past-hearing", "proceeding_stage": "sentencing",
        "reflection_text": "spam", "submitted_by_name": "bot", "website": "http://spam.example",
    })
    assert r.status_code == 201  # pretends success
    assert client.get("/api/archive").json() == []  # nothing actually created


def test_profane_reflection_is_rejected(client):
    r = client.post("/api/archive", json={
        "hearing_id": "past-hearing", "proceeding_stage": "sentencing",
        "reflection_text": "this was total bullshit", "submitted_by_name": "A. Student",
    })
    assert r.status_code == 400


def test_justice_marking_attendance_needs_no_reflection_and_adds_self_as_attendee(client):
    headers = _auth(client)
    r = client.post("/api/archive", json={
        "hearing_id": "past-hearing", "proceeding_stage": "jury_selection",
        "submitted_by_name": "ignored for a justice",
    }, headers=headers)
    assert r.status_code == 201
    body = r.json()
    assert body["submitted_by_role"] == "justice"
    assert body["submitted_by_name"] == "Joshua Loehr"
    assert body["attendees"] == ["Joshua Loehr"]
    assert body["reflection_text"] is None


def test_archive_is_filterable_and_reverse_chronological(client):
    client.post("/api/archive", json={
        "hearing_id": "past-hearing", "proceeding_stage": "sentencing",
        "reflection_text": "First real entry, worth reading.", "submitted_by_name": "A",
    })
    client.post("/api/archive", json={
        "hearing_id": "past-hearing", "proceeding_stage": "jury_selection",
        "reflection_text": "Second real entry, also worth reading.", "submitted_by_name": "B",
    })

    all_entries = client.get("/api/archive").json()
    assert len(all_entries) == 2
    assert all_entries[0]["submitted_by_name"] == "B"  # newest first

    filtered = client.get("/api/archive", params={"proceeding_stage": "sentencing"}).json()
    assert len(filtered) == 1
    assert filtered[0]["submitted_by_name"] == "A"

    by_category = client.get("/api/archive", params={"case_category": "criminal"}).json()
    assert len(by_category) == 2  # past-hearing is criminal


def test_any_justice_can_edit_or_remove_any_entry(client):
    created = client.post("/api/archive", json={
        "hearing_id": "past-hearing", "proceeding_stage": "sentencing",
        "reflection_text": "Original text worth writing down here.", "submitted_by_name": "A. Student",
    }).json()

    headers = _auth(client)
    edited = client.patch(f"/api/archive/{created['id']}", json={"judge_name": "Hon. Jane Ortiz"}, headers=headers)
    assert edited.status_code == 200
    assert edited.json()["judge_name"] == "Hon. Jane Ortiz"

    removed = client.delete(f"/api/archive/{created['id']}", headers=headers)
    assert removed.status_code == 200
    assert client.get("/api/archive").json() == []


def test_editing_or_removing_requires_a_justice_login(client):
    created = client.post("/api/archive", json={
        "hearing_id": "past-hearing", "proceeding_stage": "sentencing",
        "reflection_text": "Original text worth writing down here.", "submitted_by_name": "A. Student",
    }).json()

    assert client.patch(f"/api/archive/{created['id']}", json={"judge_name": "x"}).status_code == 401
    assert client.delete(f"/api/archive/{created['id']}").status_code == 401

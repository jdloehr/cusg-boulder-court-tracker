"""
Tests for the CUSG Justice features (attendance RSVP + recommendation
board) -- not in the original build prompt, added on request. Follows the
same TestClient + isolated in-memory-DB pattern as
test_community_submissions.py.
"""
from datetime import date

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


@pytest.fixture()
def client():
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
    hearing = Hearing(
        id="hearing-1",
        source=HearingSource.state_docket_export,
        case_number="2026CR000123",
        case_category=CaseCategory.criminal,
        hearing_type_raw="Jury Trial",
        hearing_type_display="Jury Trial",
        hearing_type_category=HearingTypeCategory.jury_trial.value,
        date=date(2026, 10, 1),
        court_location=CourtLocation.boulder_county,
        appearance_type=AppearanceType.in_person,
        status=HearingStatus.scheduled,
    )
    chief = AdminUser(email="dillon@test.local", hashed_password=hash_password("pw"),
                       is_justice=True, display_name="Dillon Rankin", title="Chief Justice")
    associate = AdminUser(email="joshua@test.local", hashed_password=hash_password("pw"),
                           is_justice=True, display_name="Joshua Loehr", title="Associate Justice")
    non_justice = AdminUser(email="editor@test.local", hashed_password=hash_password("pw"), role=None)
    seed.add_all([hearing, chief, associate, non_justice])
    seed.commit()
    seed.close()

    yield TestClient(app)
    app.dependency_overrides.clear()


def _login(client, email):
    r = client.post("/api/admin/login", json={"email": email, "password": "pw"})
    assert r.status_code == 200
    return r.json()


def test_justice_roster_is_public(client):
    r = client.get("/api/justices")
    assert r.status_code == 200
    names = {j["display_name"] for j in r.json()}
    assert names == {"Dillon Rankin", "Joshua Loehr"}


def test_login_response_carries_justice_identity(client):
    body = _login(client, "dillon@test.local")
    assert body["is_justice"] is True
    assert body["display_name"] == "Dillon Rankin"
    assert body["title"] == "Chief Justice"
    assert body["role"] is None


def test_non_justice_cannot_set_attendance(client):
    token = _login(client, "editor@test.local")["access_token"]
    r = client.put("/api/hearings/hearing-1/attendance",
                    json={"status": "attending"}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_justice_can_set_and_update_own_attendance(client):
    token = _login(client, "dillon@test.local")["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    r = client.put("/api/hearings/hearing-1/attendance",
                    json={"status": "maybe", "note": "depends on my class schedule"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "maybe"

    # updating again should replace, not duplicate
    r2 = client.put("/api/hearings/hearing-1/attendance", json={"status": "attending"}, headers=headers)
    assert r2.status_code == 200
    assert r2.json()["status"] == "attending"

    hearing = client.get("/api/hearings/hearing-1").json()
    assert len(hearing["attendance"]) == 1
    assert hearing["attendance"][0]["display_name"] == "Dillon Rankin"
    assert hearing["attendance"][0]["status"] == "attending"


def test_two_justices_attendance_is_independent(client):
    dillon_token = _login(client, "dillon@test.local")["access_token"]
    joshua_token = _login(client, "joshua@test.local")["access_token"]

    client.put("/api/hearings/hearing-1/attendance", json={"status": "attending"},
               headers={"Authorization": f"Bearer {dillon_token}"})
    client.put("/api/hearings/hearing-1/attendance", json={"status": "not_attending"},
               headers={"Authorization": f"Bearer {joshua_token}"})

    hearing = client.get("/api/hearings/hearing-1").json()
    statuses = {a["display_name"]: a["status"] for a in hearing["attendance"]}
    assert statuses == {"Dillon Rankin": "attending", "Joshua Loehr": "not_attending"}


def test_recommendation_board_is_public_but_writes_need_a_justice(client):
    r = client.get("/api/recommendations")
    assert r.status_code == 200
    assert r.json() == []

    editor_token = _login(client, "editor@test.local")["access_token"]
    denied = client.post("/api/recommendations", json={"hearing_id": "hearing-1", "note": "worth it"},
                          headers={"Authorization": f"Bearer {editor_token}"})
    assert denied.status_code == 403

    joshua_token = _login(client, "joshua@test.local")["access_token"]
    created = client.post("/api/recommendations",
                           json={"hearing_id": "hearing-1", "note": "Good example of voir dire"},
                           headers={"Authorization": f"Bearer {joshua_token}"})
    assert created.status_code == 201
    assert created.json()["justice_display_name"] == "Joshua Loehr"

    board = client.get("/api/recommendations").json()
    assert len(board) == 1
    assert board[0]["note"] == "Good example of voir dire"
    assert board[0]["hearing_case_number"] == "2026CR000123"


def test_any_justice_can_remove_a_recommendation(client):
    joshua_token = _login(client, "joshua@test.local")["access_token"]
    dillon_token = _login(client, "dillon@test.local")["access_token"]

    rec = client.post("/api/recommendations", json={"hearing_id": "hearing-1", "note": "x"},
                       headers={"Authorization": f"Bearer {joshua_token}"}).json()

    removed = client.delete(f"/api/recommendations/{rec['id']}",
                             headers={"Authorization": f"Bearer {dillon_token}"})
    assert removed.status_code == 200
    assert client.get("/api/recommendations").json() == []

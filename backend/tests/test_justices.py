"""
Tests for the CUSG Justice features (attendance RSVP + recommendation
board) -- not in the original build prompt, added on request. Follows the
same TestClient + isolated in-memory-DB pattern as
test_community_submissions.py.

Both features require a real Justice login (`require_justice`) -- this
reverses an earlier build-session decision that made them fully open with
no login at all (see justices.py's module docstring for why it changed
back).
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


def _auth(client, email):
    token = _login(client, email)["access_token"]
    return {"Authorization": f"Bearer {token}"}


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


def test_setting_attendance_requires_a_justice_login(client):
    r = client.put("/api/hearings/hearing-1/attendance", json={"status": "attending"})
    assert r.status_code == 401  # no token at all

    non_justice_headers = _auth(client, "editor@test.local")
    r2 = client.put("/api/hearings/hearing-1/attendance", json={"status": "attending"}, headers=non_justice_headers)
    assert r2.status_code == 403  # logged in, but not a Justice


def test_setting_attendance_as_a_justice_uses_the_logged_in_identity(client):
    headers = _auth(client, "dillon@test.local")
    r = client.put("/api/hearings/hearing-1/attendance", json={"status": "attending"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["display_name"] == "Dillon Rankin"


def test_setting_attendance_again_updates_not_duplicates(client):
    headers = _auth(client, "dillon@test.local")

    r = client.put("/api/hearings/hearing-1/attendance",
                    json={"status": "maybe", "note": "depends on my class schedule"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "maybe"

    r2 = client.put("/api/hearings/hearing-1/attendance", json={"status": "attending"}, headers=headers)
    assert r2.status_code == 200
    assert r2.json()["status"] == "attending"

    hearing = client.get("/api/hearings/hearing-1").json()
    assert len(hearing["attendance"]) == 1
    assert hearing["attendance"][0]["display_name"] == "Dillon Rankin"
    assert hearing["attendance"][0]["status"] == "attending"


def test_two_justices_attendance_is_independent(client):
    dillon_headers = _auth(client, "dillon@test.local")
    joshua_headers = _auth(client, "joshua@test.local")

    client.put("/api/hearings/hearing-1/attendance", json={"status": "attending"}, headers=dillon_headers)
    client.put("/api/hearings/hearing-1/attendance", json={"status": "not_attending"}, headers=joshua_headers)

    hearing = client.get("/api/hearings/hearing-1").json()
    statuses = {a["display_name"]: a["status"] for a in hearing["attendance"]}
    assert statuses == {"Dillon Rankin": "attending", "Joshua Loehr": "not_attending"}


def test_recommendation_board_is_public_to_read_but_needs_login_to_write(client):
    r = client.get("/api/recommendations")
    assert r.status_code == 200
    assert r.json() == []

    denied = client.post("/api/recommendations", json={"hearing_id": "hearing-1", "note": "Good example of voir dire"})
    assert denied.status_code == 401

    headers = _auth(client, "joshua@test.local")
    created = client.post("/api/recommendations",
                           json={"hearing_id": "hearing-1", "note": "Good example of voir dire"}, headers=headers)
    assert created.status_code == 201
    assert created.json()["justice_display_name"] == "Joshua Loehr"

    board = client.get("/api/recommendations").json()
    assert len(board) == 1
    assert board[0]["note"] == "Good example of voir dire"
    assert board[0]["hearing_case_number"] == "2026CR000123"


def test_recommendations_filterable_by_hearing_id_for_the_detail_page_callout(client):
    headers = _auth(client, "joshua@test.local")
    client.post("/api/recommendations", json={"hearing_id": "hearing-1", "note": "first reason"}, headers=headers)

    filtered = client.get("/api/recommendations", params={"hearing_id": "hearing-1"}).json()
    assert len(filtered) == 1

    missing = client.get("/api/recommendations", params={"hearing_id": "not-a-real-hearing"}).json()
    assert missing == []


def test_multiple_justices_can_recommend_the_same_hearing_without_overwriting(client):
    dillon_headers = _auth(client, "dillon@test.local")
    joshua_headers = _auth(client, "joshua@test.local")
    client.post("/api/recommendations", json={"hearing_id": "hearing-1", "note": "reason one"}, headers=dillon_headers)
    client.post("/api/recommendations", json={"hearing_id": "hearing-1", "note": "reason two"}, headers=joshua_headers)

    board = client.get("/api/recommendations", params={"hearing_id": "hearing-1"}).json()
    assert len(board) == 2
    assert {r["justice_display_name"] for r in board} == {"Dillon Rankin", "Joshua Loehr"}


def test_recommendation_requires_a_non_empty_reason(client):
    headers = _auth(client, "joshua@test.local")
    r = client.post("/api/recommendations", json={"hearing_id": "hearing-1", "note": "   "}, headers=headers)
    assert r.status_code == 422


def test_removing_a_recommendation_requires_a_justice_login(client):
    headers = _auth(client, "joshua@test.local")
    rec = client.post("/api/recommendations", json={"hearing_id": "hearing-1", "note": "x"}, headers=headers).json()

    denied = client.delete(f"/api/recommendations/{rec['id']}")
    assert denied.status_code == 401

    # a different Justice can still remove it (small, trusted roster)
    dillon_headers = _auth(client, "dillon@test.local")
    removed = client.delete(f"/api/recommendations/{rec['id']}", headers=dillon_headers)
    assert removed.status_code == 200
    assert client.get("/api/recommendations").json() == []


def test_new_recommendation_emails_every_justice_and_separate_subscribers(client, monkeypatch):
    sent = []
    monkeypatch.setattr("app.jobs.digest.send_email", lambda to, subject, body: sent.append((to, subject, body)))

    client.post("/api/subscriptions", json={
        "email": "watcher@example.com", "filter_type": "new_recommendation",
        "filter_value": "all", "frequency": "realtime_for_followed_case",
    })
    # A weekly-digest subscriber to something else shouldn't get either email.
    client.post("/api/subscriptions", json={
        "email": "other@example.com", "filter_type": "hearing_type_category",
        "filter_value": "jury_trial", "frequency": "weekly_digest",
    })

    headers = _auth(client, "joshua@test.local")
    client.post("/api/recommendations", json={"hearing_id": "hearing-1", "note": "worth it"}, headers=headers)

    recipients = {to for to, _, _ in sent}
    # every Justice (2 seeded) + the one public subscriber, not the weekly-digest one
    assert recipients == {"dillon@test.local", "joshua@test.local", "watcher@example.com"}
    justice_email = next(body for to, subject, body in sent if to == "dillon@test.local")
    assert "Joshua Loehr" in justice_email
    assert "worth it" in justice_email

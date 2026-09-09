"""
End-to-end tests for the public "add details about this case" feature
(Section 4's guardrails extended to visitor-submitted content, not just the
automated pipelines -- see docs/EXCLUSION_LOGIC.md). Uses a real FastAPI
TestClient against an isolated in-memory DB, not just direct ORM calls, so
the auth/role gating on the review endpoints is actually exercised.
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
    AdminRole,
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
    # StaticPool: without it, every new Session() grabs a fresh (and
    # separately empty) `:memory:` database instead of sharing the one
    # this fixture seeds.
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
    editor = AdminUser(email="editor@test.local", hashed_password=hash_password("pw"), role=AdminRole.editor)
    contributor = AdminUser(email="contrib@test.local", hashed_password=hash_password("pw"), role=AdminRole.contributor)
    seed.add_all([hearing, editor, contributor])
    seed.commit()
    seed.close()

    yield TestClient(app)
    app.dependency_overrides.clear()


def _login(client, email, password="pw"):
    r = client.post("/api/admin/login", json={"email": email, "password": password})
    assert r.status_code == 200
    return r.json()["access_token"]


def test_public_submission_requires_at_least_one_field(client):
    r = client.post("/api/hearings/hearing-1/submissions", json={})
    assert r.status_code == 400


def test_public_submission_honeypot_silently_no_ops(client):
    r = client.post("/api/hearings/hearing-1/submissions",
                     json={"summary_text": "spam", "website": "http://spam.example"})
    assert r.status_code == 201
    token = _login(client, "editor@test.local")
    queue = client.get("/api/admin/review-queue/community-submissions",
                        headers={"Authorization": f"Bearer {token}"}).json()
    assert queue == []  # never actually created


def test_public_submission_over_length_rejected(client):
    r = client.post("/api/hearings/hearing-1/submissions", json={"judge_name": "x" * 200})
    assert r.status_code == 422


def test_submission_is_not_public_until_approved(client):
    r = client.post("/api/hearings/hearing-1/submissions",
                     json={"summary_text": "This case involves a notable dispute.", "judge_name": "Hon. Jane Ortiz"})
    assert r.status_code == 201

    hearing = client.get("/api/hearings/hearing-1").json()
    assert hearing["judge_name"] is None
    assert hearing["community_submissions"] == []


def test_contributor_cannot_approve_but_can_view_queue(client):
    client.post("/api/hearings/hearing-1/submissions", json={"judge_name": "Hon. Jane Ortiz"})
    contrib_token = _login(client, "contrib@test.local")

    queue = client.get("/api/admin/review-queue/community-submissions",
                        headers={"Authorization": f"Bearer {contrib_token}"})
    assert queue.status_code == 200
    assert len(queue.json()) == 1
    submission_id = queue.json()[0]["id"]

    denied = client.post(f"/api/admin/community-submissions/{submission_id}/approve",
                          headers={"Authorization": f"Bearer {contrib_token}"})
    assert denied.status_code == 403


def test_editor_approve_publishes_judge_name_and_summary(client):
    client.post("/api/hearings/hearing-1/submissions",
                json={"summary_text": "Worth attending for the cross-examination.", "judge_name": "Hon. Jane Ortiz"})
    editor_token = _login(client, "editor@test.local")
    submission_id = client.get(
        "/api/admin/review-queue/community-submissions", headers={"Authorization": f"Bearer {editor_token}"}
    ).json()[0]["id"]

    approve = client.post(f"/api/admin/community-submissions/{submission_id}/approve",
                           headers={"Authorization": f"Bearer {editor_token}"})
    assert approve.status_code == 200

    hearing = client.get("/api/hearings/hearing-1").json()
    assert hearing["judge_name"] == "Hon. Jane Ortiz"
    assert len(hearing["community_submissions"]) == 1
    assert hearing["community_submissions"][0]["summary_text"] == "Worth attending for the cross-examination."

    # resolved out of the pending queue
    queue = client.get("/api/admin/review-queue/community-submissions",
                        headers={"Authorization": f"Bearer {editor_token}"}).json()
    assert queue == []


def test_editor_reject_keeps_it_off_the_public_hearing(client):
    client.post("/api/hearings/hearing-1/submissions", json={"judge_name": "Hon. Someone Wrong"})
    editor_token = _login(client, "editor@test.local")
    submission_id = client.get(
        "/api/admin/review-queue/community-submissions", headers={"Authorization": f"Bearer {editor_token}"}
    ).json()[0]["id"]

    reject = client.post(f"/api/admin/community-submissions/{submission_id}/reject",
                          headers={"Authorization": f"Bearer {editor_token}"})
    assert reject.status_code == 200

    hearing = client.get("/api/hearings/hearing-1").json()
    assert hearing["judge_name"] is None

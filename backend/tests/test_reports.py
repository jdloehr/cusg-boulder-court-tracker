"""
Phase-4 doc, Section 2.5: "Report" flagging on Archive entries and
recommendations, notifying every Justice (Section 5.4's explicit choice).
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
    AdminRole,
    AdminUser,
    AppearanceType,
    ArchiveEntry,
    ArchiveSubmitterRole,
    Base,
    CaseCategory,
    CourtLocation,
    Hearing,
    HearingRecommendation,
    HearingSource,
    HearingStatus,
    HearingTypeCategory,
    ProceedingStage,
)
from app.rate_limit import reset_for_tests


@pytest.fixture()
def ctx():
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

    seed = TestSession()
    hearing = Hearing(
        id="hearing-1", source=HearingSource.state_docket_export, case_number="2026CR000123",
        case_category=CaseCategory.criminal, hearing_type_raw="Jury Trial", hearing_type_display="Jury Trial",
        hearing_type_category=HearingTypeCategory.jury_trial.value, date=date.today() - timedelta(days=2),
        court_location=CourtLocation.boulder_county, appearance_type=AppearanceType.in_person,
        status=HearingStatus.scheduled,
    )
    justice = AdminUser(email="joshua@test.local", hashed_password=hash_password("pw"),
                         is_justice=True, role=AdminRole.editor, display_name="Joshua Loehr")
    editor = AdminUser(email="editor@test.local", hashed_password=hash_password("editor-pw-123"),
                        role=AdminRole.editor, display_name="Editor Editorson")
    seed.add_all([hearing, justice, editor])
    seed.commit()

    entry = ArchiveEntry(id="entry-1", hearing_id=hearing.id, proceeding_stage=ProceedingStage.other,
                          reflection_text="A reflection that later turns out to be a problem.",
                          submitted_by_name="A. Student", submitted_by_role=ArchiveSubmitterRole.regular_user)
    rec = HearingRecommendation(id="rec-1", hearing_id=hearing.id, justice_id=justice.id, note="Worth watching")
    seed.add_all([entry, rec])
    seed.commit()
    seed.close()

    yield TestClient(app), TestSession
    app.dependency_overrides.clear()


def _auth(client, email="editor@test.local", password="editor-pw-123"):
    r = client.post("/api/admin/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_anyone_can_report_an_archive_entry_and_every_justice_is_emailed(ctx, monkeypatch):
    client, _Session = ctx
    sent = []
    monkeypatch.setattr("app.jobs.digest.send_email", lambda to, subject, body: sent.append(to))

    r = client.post("/api/reports", json={
        "target_type": "archive_entry", "target_id": "entry-1", "reason": "This seems made up.",
    })
    assert r.status_code == 201, r.text
    assert sent == ["joshua@test.local"]


def test_reporting_a_recommendation_works_too(ctx):
    client, _Session = ctx
    r = client.post("/api/reports", json={"target_type": "recommendation", "target_id": "rec-1"})
    assert r.status_code == 201


def test_reporting_something_nonexistent_404s(ctx):
    client, _Session = ctx
    r = client.post("/api/reports", json={"target_type": "archive_entry", "target_id": "no-such-id"})
    assert r.status_code == 404


def test_honeypot_silently_no_ops(ctx, monkeypatch):
    client, _Session = ctx
    sent = []
    monkeypatch.setattr("app.jobs.digest.send_email", lambda to, subject, body: sent.append(to))
    r = client.post("/api/reports", json={
        "target_type": "archive_entry", "target_id": "entry-1", "website": "http://spam.example",
    })
    assert r.status_code == 201
    assert sent == []


def test_report_is_rate_limited(ctx):
    client, _Session = ctx
    for _ in range(10):
        client.post("/api/reports", json={"target_type": "archive_entry", "target_id": "entry-1"})
    blocked = client.post("/api/reports", json={"target_type": "archive_entry", "target_id": "entry-1"})
    assert blocked.status_code == 429


def test_editor_can_see_and_resolve_reports(ctx):
    client, _Session = ctx
    client.post("/api/reports", json={"target_type": "archive_entry", "target_id": "entry-1", "reason": "spam?"})
    headers = _auth(client)

    queue = client.get("/api/admin/reports", headers=headers)
    assert queue.status_code == 200
    reports = queue.json()
    assert len(reports) == 1
    assert reports[0]["target_summary"].startswith("A reflection")
    report_id = reports[0]["id"]

    resolved = client.post(f"/api/admin/reports/{report_id}/resolve", headers=headers)
    assert resolved.status_code == 200

    still_open = client.get("/api/admin/reports", headers=headers).json()
    assert still_open == []

    resolved_list = client.get("/api/admin/reports?resolved=true", headers=headers).json()
    assert len(resolved_list) == 1


def test_non_editor_cannot_see_the_reports_queue(ctx):
    client, Session = ctx
    db = Session()
    db.add(AdminUser(email="contributor@test.local", hashed_password=hash_password("contrib-pw-123"),
                      role=AdminRole.contributor))
    db.commit()
    db.close()
    headers = _auth(client, "contributor@test.local", "contrib-pw-123")
    r = client.get("/api/admin/reports", headers=headers)
    assert r.status_code == 403


def test_reporter_ip_never_exposed_in_the_queue(ctx):
    client, _Session = ctx
    client.post("/api/reports", json={"target_type": "archive_entry", "target_id": "entry-1"})
    headers = _auth(client)
    body = client.get("/api/admin/reports", headers=headers).json()
    assert "reporter_ip" not in body[0]

"""
Tests for DELETE /api/admin/justices/{id} -- added after a real production
incident: Avery Talbott ended up with two AdminUser rows (an empty stub
from one invite-accept, a filled-in one from another), and there was no
way to remove the stub short of a direct database edit. See
routers/account.py::remove_justice for the cascading-cleanup reasoning.
"""
from datetime import date, datetime

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
    ArchiveEntry,
    ArchiveSubmitterRole,
    AppearanceType,
    AttendanceStatus,
    AvailabilityOwnerType,
    AvailabilitySlot,
    Base,
    CaseCategory,
    CourtLocation,
    DayOfWeek,
    Hearing,
    HearingAttendance,
    HearingRecommendation,
    HearingSource,
    HearingStatus,
    HearingTypeCategory,
    PasswordResetToken,
    ProceedingStage,
)
from app.rate_limit import reset_for_tests


@pytest.fixture()
def client():
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
    editor = AdminUser(email="editor@test.local", hashed_password=hash_password("pw"),
                        is_justice=True, display_name="Dillon Rankin", role=AdminRole.editor)
    stub = AdminUser(email="avery-stub@test.local", hashed_password=hash_password("pw"),
                      is_justice=True, display_name="Avery Talbott (stub)", role=AdminRole.editor)
    seed.add_all([hearing, editor, stub])
    seed.commit()
    stub_id, editor_id = stub.id, editor.id

    # Dependent rows that must be cleaned up for the delete to succeed at all.
    seed.add(HearingAttendance(hearing_id="hearing-1", justice_id=stub_id, status=AttendanceStatus.attending))
    seed.add(HearingRecommendation(hearing_id="hearing-1", justice_id=stub_id, note="worth it"))
    seed.add(PasswordResetToken(admin_user_id=stub_id, token_hash="x" * 64,
                                 expires_at=datetime(2099, 1, 1)))
    seed.add(AvailabilitySlot(owner_type=AvailabilityOwnerType.justice, owner_id=stub_id,
                               day_of_week=DayOfWeek.mon, slot_index=0))
    seed.add(ArchiveEntry(hearing_id="hearing-1", proceeding_stage=ProceedingStage.other,
                           submitted_by_name="Avery Talbott", submitted_by_role=ArchiveSubmitterRole.justice,
                           submitted_by_justice_id=stub_id))
    seed.commit()
    seed.close()

    yield TestClient(app), stub_id, editor_id
    app.dependency_overrides.clear()


def _auth(client, email):
    r = client.post("/api/admin/login", json={"email": email, "password": "pw"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_remove_justice_requires_editor_login(client):
    tc, stub_id, _editor_id = client
    r = tc.delete(f"/api/admin/justices/{stub_id}")
    assert r.status_code == 401


def test_remove_justice_as_an_editor_succeeds(client):
    tc, stub_id, _editor_id = client
    headers = _auth(tc, "editor@test.local")
    r = tc.delete(f"/api/admin/justices/{stub_id}", headers=headers)
    assert r.status_code == 200


def test_remove_justice_deletes_the_account_and_its_dependent_rows(client):
    tc, stub_id, _editor_id = client
    headers = _auth(tc, "editor@test.local")

    r = tc.delete(f"/api/admin/justices/{stub_id}", headers=headers)
    assert r.status_code == 200
    assert r.json() == {"status": "removed"}

    roster = tc.get("/api/justices").json()
    assert stub_id not in {j["id"] for j in roster}

    hearing = tc.get("/api/hearings/hearing-1").json()
    assert hearing["attendance"] == []

    board = tc.get("/api/recommendations").json()
    assert board == []


def test_remove_justice_nulls_out_archive_byline_instead_of_deleting_the_entry(client):
    tc, stub_id, _editor_id = client
    headers = _auth(tc, "editor@test.local")

    before = tc.get("/api/archive").json()
    assert len(before) == 1

    tc.delete(f"/api/admin/justices/{stub_id}", headers=headers)

    after = tc.get("/api/archive").json()
    assert len(after) == 1  # the entry itself survives
    assert after[0]["submitted_by_name"] == "Avery Talbott"  # plain-text byline untouched


def test_cannot_remove_your_own_account(client):
    tc, _stub_id, editor_id = client
    headers = _auth(tc, "editor@test.local")
    r = tc.delete(f"/api/admin/justices/{editor_id}", headers=headers)
    assert r.status_code == 400


def test_remove_justice_404s_for_an_unknown_id(client):
    tc, _stub_id, _editor_id = client
    headers = _auth(tc, "editor@test.local")
    r = tc.delete("/api/admin/justices/not-a-real-id", headers=headers)
    assert r.status_code == 404

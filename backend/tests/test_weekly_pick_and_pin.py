"""
Page-redesign doc: two real "featured" flags backing the homepage's
"This Week's Pick" spotlight (Hearing.is_weekly_pick) and the
Recommendations page's Lead card (HearingRecommendation.is_pinned).
Both are "exactly one row True at a time," enforced in the router by
clearing every other row in the same transaction -- these tests exercise
that invariant directly, plus role-gating and 404s. Same ctx/TestClient
fixture style as tests/test_learn.py.
"""
import json
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
    HearingRecommendation,
    HearingSource,
    HearingStatus,
    HearingTypeCategory,
)
from app.rate_limit import reset_for_tests


def _hearing(**overrides):
    defaults = dict(
        source=HearingSource.state_docket_export, case_category=CaseCategory.criminal,
        party_names=json.dumps(["Alex Dawson"]), hearing_type_raw="Jury Trial",
        hearing_type_display="Jury Trial", hearing_type_category=HearingTypeCategory.jury_trial.value,
        date=date(2026, 12, 1), court_location=CourtLocation.boulder_county,
        appearance_type=AppearanceType.in_person, status=HearingStatus.scheduled,
    )
    defaults.update(overrides)
    return Hearing(**defaults)


@pytest.fixture()
def ctx():
    reset_for_tests()
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)

    def override_get_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db

    seed = TestSession()
    editor = AdminUser(id="editor-1", email="editor@test.local", hashed_password=hash_password("pw"),
                        role=AdminRole.editor, is_justice=True, display_name="Chief Justice Test")
    contributor = AdminUser(id="contributor-1", email="contributor@test.local", hashed_password=hash_password("pw"),
                             role=AdminRole.contributor)
    hearing_a = _hearing(id="hearing-a", case_number="2026CR000001")
    hearing_b = _hearing(id="hearing-b", case_number="2026CR000002")
    rec_a = HearingRecommendation(id="rec-a", hearing_id="hearing-a", justice_id="editor-1", note="Watch this.")
    rec_b = HearingRecommendation(id="rec-b", hearing_id="hearing-b", justice_id="editor-1", note="Also good.")
    seed.add_all([editor, contributor, hearing_a, hearing_b, rec_a, rec_b])
    seed.commit()
    seed.close()

    yield TestClient(app), TestSession
    app.dependency_overrides.clear()


def _auth(client, email="editor@test.local"):
    r = client.post("/api/admin/login", json={"email": email, "password": "pw"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# --- This Week's Pick --------------------------------------------------------

def test_set_weekly_pick_marks_the_hearing(ctx):
    client, _Session = ctx
    r = client.post("/api/admin/hearings/hearing-a/set-weekly-pick", headers=_auth(client))
    assert r.status_code == 200
    public = client.get("/api/hearings/hearing-a").json()
    assert public["is_weekly_pick"] is True


def test_set_weekly_pick_clears_the_previous_one(ctx):
    client, _Session = ctx
    headers = _auth(client)
    client.post("/api/admin/hearings/hearing-a/set-weekly-pick", headers=headers)
    client.post("/api/admin/hearings/hearing-b/set-weekly-pick", headers=headers)

    a = client.get("/api/hearings/hearing-a").json()
    b = client.get("/api/hearings/hearing-b").json()
    assert a["is_weekly_pick"] is False
    assert b["is_weekly_pick"] is True


def test_clear_weekly_pick(ctx):
    client, _Session = ctx
    headers = _auth(client)
    client.post("/api/admin/hearings/hearing-a/set-weekly-pick", headers=headers)
    client.post("/api/admin/hearings/hearing-a/clear-weekly-pick", headers=headers)
    a = client.get("/api/hearings/hearing-a").json()
    assert a["is_weekly_pick"] is False


def test_set_weekly_pick_requires_editor(ctx):
    client, _Session = ctx
    r = client.post("/api/admin/hearings/hearing-a/set-weekly-pick", headers=_auth(client, "contributor@test.local"))
    assert r.status_code == 403


def test_set_weekly_pick_requires_login(ctx):
    client, _Session = ctx
    r = client.post("/api/admin/hearings/hearing-a/set-weekly-pick")
    assert r.status_code == 401


def test_set_weekly_pick_404s_for_unknown_hearing(ctx):
    client, _Session = ctx
    r = client.post("/api/admin/hearings/does-not-exist/set-weekly-pick", headers=_auth(client))
    assert r.status_code == 404


def test_hearing_defaults_to_not_the_pick(ctx):
    client, _Session = ctx
    b = client.get("/api/hearings/hearing-b").json()
    assert b["is_weekly_pick"] is False


def test_set_weekly_pick_rejects_a_remote_hearing(ctx):
    """Oct 2026 review, Phase 2 item 2: "This Week's Pick" is a
    spotlight meant to get someone to go sit in on a hearing -- a
    remote one isn't something a visitor can show up and watch."""
    client, Session = ctx
    db = Session()
    db.add(_hearing(id="hearing-remote", case_number="2026CR000003", appearance_type=AppearanceType.remote))
    db.commit()
    db.close()

    r = client.post("/api/admin/hearings/hearing-remote/set-weekly-pick", headers=_auth(client))
    assert r.status_code == 400
    assert client.get("/api/hearings/hearing-remote").json()["is_weekly_pick"] is False


# --- GET /api/hearings/weekly-pick --------------------------------------------

def test_weekly_pick_endpoint_returns_null_when_nothing_is_picked(ctx):
    client, _Session = ctx
    r = client.get("/api/hearings/weekly-pick")
    assert r.status_code == 200
    assert r.json() is None


def test_weekly_pick_endpoint_returns_the_real_pick(ctx):
    client, _Session = ctx
    client.post("/api/admin/hearings/hearing-a/set-weekly-pick", headers=_auth(client))
    r = client.get("/api/hearings/weekly-pick")
    assert r.status_code == 200
    assert r.json()["id"] == "hearing-a"


def test_weekly_pick_endpoint_finds_a_pick_outside_the_default_lists_date_window(ctx):
    """Real bug this fixes: GET /api/hearings only shows the next 14
    days by default -- Home.jsx used to search *that* list for
    is_weekly_pick, so a real pick further out silently vanished from
    the search and the page fell back to a heuristic under the same
    label. This endpoint has no such window."""
    client, Session = ctx
    db = Session()
    db.add(_hearing(id="hearing-far-out", case_number="2026CR000004", date=date(2027, 3, 1)))
    db.commit()
    db.close()

    client.post("/api/admin/hearings/hearing-far-out/set-weekly-pick", headers=_auth(client))

    # Confirms the bug scenario: the far-out pick is NOT in the default list.
    default_list_ids = {h["id"] for h in client.get("/api/hearings").json()}
    assert "hearing-far-out" not in default_list_ids

    # But the dedicated endpoint finds it directly either way.
    r = client.get("/api/hearings/weekly-pick")
    assert r.json()["id"] == "hearing-far-out"


def test_weekly_pick_endpoint_hides_a_pick_that_was_since_excluded(ctx):
    client, Session = ctx
    client.post("/api/admin/hearings/hearing-a/set-weekly-pick", headers=_auth(client))

    db = Session()
    hearing = db.query(Hearing).filter(Hearing.id == "hearing-a").first()
    hearing.is_excluded = True
    db.commit()
    db.close()

    assert client.get("/api/hearings/weekly-pick").json() is None


def test_weekly_pick_endpoint_hides_a_pick_that_was_since_cancelled(ctx):
    client, Session = ctx
    client.post("/api/admin/hearings/hearing-a/set-weekly-pick", headers=_auth(client))

    db = Session()
    hearing = db.query(Hearing).filter(Hearing.id == "hearing-a").first()
    hearing.status = HearingStatus.cancelled
    db.commit()
    db.close()

    assert client.get("/api/hearings/weekly-pick").json() is None


# --- Recommendation pin -------------------------------------------------------

def test_pin_recommendation(ctx):
    client, _Session = ctx
    r = client.post("/api/recommendations/rec-a/pin", headers=_auth(client))
    assert r.status_code == 200, r.text
    assert r.json()["is_pinned"] is True

    listed = {rec["id"]: rec for rec in client.get("/api/recommendations").json()}
    assert listed["rec-a"]["is_pinned"] is True
    assert listed["rec-b"]["is_pinned"] is False


def test_pin_recommendation_clears_the_previous_one(ctx):
    client, _Session = ctx
    headers = _auth(client)
    client.post("/api/recommendations/rec-a/pin", headers=headers)
    client.post("/api/recommendations/rec-b/pin", headers=headers)

    listed = {rec["id"]: rec for rec in client.get("/api/recommendations").json()}
    assert listed["rec-a"]["is_pinned"] is False
    assert listed["rec-b"]["is_pinned"] is True


def test_unpin_recommendation(ctx):
    client, _Session = ctx
    headers = _auth(client)
    client.post("/api/recommendations/rec-a/pin", headers=headers)
    r = client.post("/api/recommendations/rec-a/unpin", headers=headers)
    assert r.status_code == 200
    assert r.json()["is_pinned"] is False


def test_pin_recommendation_requires_justice_login(ctx):
    client, _Session = ctx
    r = client.post("/api/recommendations/rec-a/pin")
    assert r.status_code == 401


def test_pin_recommendation_requires_a_real_justice_not_just_any_editor(ctx):
    """require_justice (identity), not require_editor (role) -- a
    Contributor account (curation role but not a real Justice) must be
    rejected, matching create_recommendation/delete_recommendation's own
    gate right next to this endpoint."""
    client, _Session = ctx
    r = client.post("/api/recommendations/rec-a/pin", headers=_auth(client, "contributor@test.local"))
    assert r.status_code == 403


def test_pin_recommendation_404s_for_unknown_id(ctx):
    client, _Session = ctx
    r = client.post("/api/recommendations/does-not-exist/pin", headers=_auth(client))
    assert r.status_code == 404


def test_recommendation_defaults_to_not_pinned(ctx):
    client, _Session = ctx
    listed = {rec["id"]: rec for rec in client.get("/api/recommendations").json()}
    assert listed["rec-a"]["is_pinned"] is False
    assert listed["rec-b"]["is_pinned"] is False

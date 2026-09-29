"""
Phase 9 doc: the "Learn" teaching feature -- a reusable LearnTopic
library matched by hearing type/case category, plus one-off
CaseTeachingNote entries attached to a specific Hearing. Unit tests for
the matching logic (app/learn.py) use the plain `db` fixture from
conftest.py; everything reachable over HTTP uses a full-stack TestClient,
same pattern as tests/test_news_review_queue.py.
"""
import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.db import get_db
from app.learn import matching_learn_topics
from app.main import app
from app.models import (
    AdminRole,
    AdminUser,
    ArchiveEntry,
    AppearanceType,
    Base,
    CaseCategory,
    CaseTeachingNote,
    CourtLocation,
    Hearing,
    HearingSource,
    HearingStatus,
    HearingTypeCategory,
    LearnTopic,
)
from app.rate_limit import reset_for_tests


def _hearing(**overrides):
    defaults = dict(
        id="hearing-1", source=HearingSource.state_docket_export, case_number="2026CR000123",
        case_category=CaseCategory.criminal, party_names=json.dumps(["Alex Dawson"]),
        hearing_type_raw="Jury Trial", hearing_type_display="Jury Trial",
        hearing_type_category=HearingTypeCategory.jury_trial.value, date=date(2026, 12, 1),
        court_location=CourtLocation.boulder_county, appearance_type=AppearanceType.in_person,
        status=HearingStatus.scheduled,
    )
    defaults.update(overrides)
    return Hearing(**defaults)


# --- Unit tests: matching_learn_topics -------------------------------------

def test_type_only_topic_matches_any_case_category(db):
    db.add(LearnTopic(id="t1", title="Jury Trials", applies_to_hearing_type_category=HearingTypeCategory.jury_trial,
                       body_text="What is a jury trial."))
    db.add(_hearing(case_category=CaseCategory.civil))
    db.commit()
    hearing = db.query(Hearing).first()
    matches = matching_learn_topics(db, hearing)
    assert [t.id for t in matches] == ["t1"]


def test_category_only_topic_matches_any_hearing_type(db):
    db.add(LearnTopic(id="t2", title="Criminal Cases", applies_to_case_category=CaseCategory.criminal,
                       body_text="What is a criminal case."))
    db.add(_hearing(hearing_type_category=HearingTypeCategory.oral_argument_motions))
    db.commit()
    hearing = db.query(Hearing).first()
    matches = matching_learn_topics(db, hearing)
    assert [t.id for t in matches] == ["t2"]


def test_both_set_topic_matches_only_that_exact_combination(db):
    db.add(LearnTopic(id="t3", title="Criminal Jury Trials", applies_to_hearing_type_category=HearingTypeCategory.jury_trial,
                       applies_to_case_category=CaseCategory.criminal, body_text="Specifics."))
    db.add(_hearing(id="h-match", case_number="A", hearing_type_category=HearingTypeCategory.jury_trial, case_category=CaseCategory.criminal))
    db.add(_hearing(id="h-nomatch", case_number="B", hearing_type_category=HearingTypeCategory.jury_trial, case_category=CaseCategory.civil))
    db.commit()
    match = db.query(Hearing).filter(Hearing.id == "h-match").first()
    nomatch = db.query(Hearing).filter(Hearing.id == "h-nomatch").first()
    assert [t.id for t in matching_learn_topics(db, match)] == ["t3"]
    assert matching_learn_topics(db, nomatch) == []


def test_hearing_can_match_more_than_one_topic(db):
    db.add(LearnTopic(id="t-type", title="Jury Trials", applies_to_hearing_type_category=HearingTypeCategory.jury_trial,
                       body_text="Type explainer."))
    db.add(LearnTopic(id="t-cat", title="Criminal Cases", applies_to_case_category=CaseCategory.criminal,
                       body_text="Category explainer."))
    db.add(_hearing())
    db.commit()
    hearing = db.query(Hearing).first()
    ids = {t.id for t in matching_learn_topics(db, hearing)}
    assert ids == {"t-type", "t-cat"}


def test_no_matching_topic_returns_empty(db):
    db.add(LearnTopic(id="t4", title="Civil Cases", applies_to_case_category=CaseCategory.civil,
                       body_text="Civil explainer."))
    db.add(_hearing(case_category=CaseCategory.criminal))
    db.commit()
    hearing = db.query(Hearing).first()
    assert matching_learn_topics(db, hearing) == []


# --- Full-stack TestClient tests --------------------------------------------

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
    editor = AdminUser(email="editor@test.local", hashed_password=hash_password("pw"), role=AdminRole.editor,
                        is_justice=True, display_name="Chief Justice Test")
    contributor = AdminUser(email="contributor@test.local", hashed_password=hash_password("pw"), role=AdminRole.contributor)
    past_hearing = _hearing(id="hearing-past", case_number="2026CR000001", date=date.today() - timedelta(days=1))
    future_hearing = _hearing(id="hearing-future", case_number="2026CR000002", date=date.today() + timedelta(days=30))
    unrelated_hearing = _hearing(id="hearing-unrelated", case_number="2026CV000003",
                                  hearing_type_category=HearingTypeCategory.other, case_category=CaseCategory.probate)
    seed.add_all([editor, contributor, past_hearing, future_hearing, unrelated_hearing])
    seed.commit()
    seed.close()

    yield TestClient(app), TestSession
    app.dependency_overrides.clear()


def _auth(client, email="editor@test.local"):
    r = client.post("/api/admin/login", json={"email": email, "password": "pw"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_create_learn_topic_requires_editor(ctx):
    client, _Session = ctx
    contributor_headers = _auth(client, "contributor@test.local")
    r = client.post("/api/admin/learn-topics", json={
        "title": "Jury Trials", "applies_to_hearing_type_category": "jury_trial", "body_text": "Explainer.",
    }, headers=contributor_headers)
    assert r.status_code == 403


def test_create_learn_topic_requires_login_at_all(ctx):
    client, _Session = ctx
    r = client.post("/api/admin/learn-topics", json={
        "title": "Jury Trials", "applies_to_hearing_type_category": "jury_trial", "body_text": "Explainer.",
    })
    assert r.status_code == 401


def test_create_learn_topic_rejects_neither_dimension_set(ctx):
    client, _Session = ctx
    r = client.post("/api/admin/learn-topics", json={"title": "Dead content", "body_text": "Matches nothing."},
                     headers=_auth(client))
    assert r.status_code == 422


def test_create_and_list_learn_topic(ctx):
    client, _Session = ctx
    r = client.post("/api/admin/learn-topics", json={
        "title": "Jury Trials", "applies_to_hearing_type_category": "jury_trial",
        "body_text": "A jury trial is...", "external_links": [{"label": "Colorado Courts", "url": "https://www.courts.state.co.us"}],
    }, headers=_auth(client))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["created_by_display_name"] == "Chief Justice Test"
    assert body["external_links"] == [{"label": "Colorado Courts", "url": "https://www.courts.state.co.us"}]

    listed = client.get("/api/learn-topics").json()
    assert len(listed) == 1
    filtered = client.get("/api/learn-topics?hearing_type_category=oral_argument_motions").json()
    assert filtered == []


def test_update_learn_topic_clearing_both_dimensions_rejected(ctx):
    client, _Session = ctx
    created = client.post("/api/admin/learn-topics", json={
        "title": "Jury Trials", "applies_to_hearing_type_category": "jury_trial", "body_text": "Explainer.",
    }, headers=_auth(client)).json()
    r = client.patch(f"/api/admin/learn-topics/{created['id']}",
                      json={"applies_to_hearing_type_category": None}, headers=_auth(client))
    assert r.status_code == 400


def test_update_learn_topic_partial(ctx):
    client, _Session = ctx
    created = client.post("/api/admin/learn-topics", json={
        "title": "Jury Trials", "applies_to_hearing_type_category": "jury_trial", "body_text": "Old text.",
    }, headers=_auth(client)).json()
    r = client.patch(f"/api/admin/learn-topics/{created['id']}", json={"body_text": "New text."}, headers=_auth(client))
    assert r.status_code == 200
    assert r.json()["body_text"] == "New text."
    assert r.json()["title"] == "Jury Trials"  # untouched


def test_delete_learn_topic(ctx):
    client, _Session = ctx
    created = client.post("/api/admin/learn-topics", json={
        "title": "Jury Trials", "applies_to_hearing_type_category": "jury_trial", "body_text": "Explainer.",
    }, headers=_auth(client)).json()
    assert client.delete(f"/api/admin/learn-topics/{created['id']}", headers=_auth(client)).status_code == 204
    assert client.get(f"/api/learn-topics/{created['id']}").status_code == 404


def test_learn_topic_video_upload_and_serve(ctx):
    client, _Session = ctx
    created = client.post("/api/admin/learn-topics", json={
        "title": "Jury Trials", "applies_to_hearing_type_category": "jury_trial", "body_text": "Explainer.",
    }, headers=_auth(client)).json()

    # Real minimal MP4 container header (ftyp box) -- enough for the
    # header-sniff check in app/video_upload.py, not a full valid video.
    fake_mp4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 100
    r = client.put(f"/api/admin/learn-topics/{created['id']}/video",
                    files={"file": ("clip.mp4", fake_mp4, "video/mp4")}, headers=_auth(client))
    assert r.status_code == 200, r.text
    assert r.json()["has_uploaded_video"] is True

    video_resp = client.get(f"/api/learn-topics/{created['id']}/video")
    assert video_resp.status_code == 200
    assert video_resp.content == fake_mp4
    assert video_resp.headers["content-type"] == "video/mp4"


def test_learn_topic_video_upload_rejects_wrong_type(ctx):
    client, _Session = ctx
    created = client.post("/api/admin/learn-topics", json={
        "title": "Jury Trials", "applies_to_hearing_type_category": "jury_trial", "body_text": "Explainer.",
    }, headers=_auth(client)).json()
    r = client.put(f"/api/admin/learn-topics/{created['id']}/video",
                    files={"file": ("doc.pdf", b"%PDF-1.4", "application/pdf")}, headers=_auth(client))
    assert r.status_code == 400


def test_learn_topic_video_upload_rejects_oversized_file(ctx):
    client, _Session = ctx
    created = client.post("/api/admin/learn-topics", json={
        "title": "Jury Trials", "applies_to_hearing_type_category": "jury_trial", "body_text": "Explainer.",
    }, headers=_auth(client)).json()
    too_big = (b"\x00\x00\x00\x18ftypmp42") + (b"\x00" * (15 * 1024 * 1024 + 1))
    r = client.put(f"/api/admin/learn-topics/{created['id']}/video",
                    files={"file": ("clip.mp4", too_big, "video/mp4")}, headers=_auth(client))
    assert r.status_code == 400
    assert "too large" in r.json()["detail"].lower()


def test_learn_topic_video_404_when_none_uploaded(ctx):
    client, _Session = ctx
    created = client.post("/api/admin/learn-topics", json={
        "title": "Jury Trials", "applies_to_hearing_type_category": "jury_trial", "body_text": "Explainer.",
    }, headers=_auth(client)).json()
    assert client.get(f"/api/learn-topics/{created['id']}/video").status_code == 404


# --- CaseTeachingNote --------------------------------------------------------

def test_create_teaching_note_requires_editor(ctx):
    client, _Session = ctx
    r = client.post("/api/admin/hearings/hearing-future/teaching-notes", json={"body_text": "Unusual case."},
                     headers=_auth(client, "contributor@test.local"))
    assert r.status_code == 403


def test_create_teaching_note_404s_for_unknown_hearing(ctx):
    client, _Session = ctx
    r = client.post("/api/admin/hearings/does-not-exist/teaching-notes", json={"body_text": "Note."}, headers=_auth(client))
    assert r.status_code == 404


def test_create_and_embed_teaching_note_on_public_hearing(ctx):
    client, Session = ctx
    r = client.post("/api/admin/hearings/hearing-future/teaching-notes",
                     json={"body_text": "This case has an unusual procedural history."}, headers=_auth(client))
    assert r.status_code == 201, r.text
    note_id = r.json()["id"]
    assert r.json()["created_by_display_name"] == "Chief Justice Test"

    public = client.get("/api/hearings/hearing-future").json()
    assert len(public["teaching_notes"]) == 1
    assert public["teaching_notes"][0]["id"] == note_id
    assert public["teaching_notes"][0]["body_text"] == "This case has an unusual procedural history."


def test_update_and_delete_teaching_note(ctx):
    client, _Session = ctx
    created = client.post("/api/admin/hearings/hearing-future/teaching-notes",
                           json={"body_text": "Original."}, headers=_auth(client)).json()
    updated = client.patch(f"/api/admin/teaching-notes/{created['id']}", json={"body_text": "Revised."}, headers=_auth(client))
    assert updated.status_code == 200
    assert updated.json()["body_text"] == "Revised."

    assert client.delete(f"/api/admin/teaching-notes/{created['id']}", headers=_auth(client)).status_code == 204
    public = client.get("/api/hearings/hearing-future").json()
    assert public["teaching_notes"] == []


def test_copy_teaching_note_to_archive_creates_real_entry(ctx):
    client, Session = ctx
    note = client.post("/api/admin/hearings/hearing-past/teaching-notes",
                        json={"body_text": "What actually happened here was unusual."}, headers=_auth(client)).json()

    r = client.post(f"/api/admin/teaching-notes/{note['id']}/copy-to-archive",
                     json={"proceeding_stage": "motions_hearing"}, headers=_auth(client))
    assert r.status_code == 201, r.text
    archived = r.json()
    assert archived["reflection_text"] == "What actually happened here was unusual."
    assert archived["hearing_id"] == "hearing-past"

    db = Session()
    entry = db.query(ArchiveEntry).filter(ArchiveEntry.id == archived["id"]).first()
    assert entry is not None
    assert entry.reflection_text == "What actually happened here was unusual."
    db.close()

    # The original note is untouched -- a copy, not a move.
    still_there = client.get("/api/hearings/hearing-past").json()
    assert len(still_there["teaching_notes"]) == 1


def test_copy_teaching_note_to_archive_rejects_future_hearing(ctx):
    """Reuses routers/archive.py::create_archive_entry's own business
    rule (can't archive a hearing that hasn't happened yet) rather than
    a hand-rolled duplicate -- so this endpoint inherits that same
    real-world constraint automatically."""
    client, _Session = ctx
    note = client.post("/api/admin/hearings/hearing-future/teaching-notes",
                        json={"body_text": "Too early to archive."}, headers=_auth(client)).json()
    r = client.post(f"/api/admin/teaching-notes/{note['id']}/copy-to-archive",
                     json={"proceeding_stage": "motions_hearing"}, headers=_auth(client))
    assert r.status_code == 400


def test_hearing_with_nothing_matching_shows_neither_section(ctx):
    """Phase 9 doc's own "before you finish" checklist item 4: invisible
    when unused."""
    client, _Session = ctx
    public = client.get("/api/hearings/hearing-unrelated").json()
    assert public["learn_topics"] == []
    assert public["teaching_notes"] == []

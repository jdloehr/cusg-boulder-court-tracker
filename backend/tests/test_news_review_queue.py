"""
Phase-6 doc, Section 4: the admin review queue for news mentions --
suggested-match confirm/reject, link-by-case-number, and the pending
count. Full-stack TestClient tests, same pattern as
test_community_submissions.py.
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
    HearingSource,
    HearingStatus,
    HearingTypeCategory,
    MatchConfidence,
    MatchStatus,
    NewsMention,
)
from app.rate_limit import reset_for_tests


@pytest.fixture()
def ctx():
    reset_for_tests()  # login is rate-limited per IP (Phase-4 doc, Section 2.3)
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
        case_category=CaseCategory.criminal, party_names=json.dumps(["Alex Dawson"]),
        hearing_type_raw="Jury Trial", hearing_type_display="Jury Trial",
        hearing_type_category=HearingTypeCategory.jury_trial.value, date=date(2026, 10, 1),
        court_location=CourtLocation.boulder_county, appearance_type=AppearanceType.in_person,
        status=HearingStatus.scheduled,
    )
    editor = AdminUser(email="editor@test.local", hashed_password=hash_password("pw"), role=AdminRole.editor)

    suggested = NewsMention(
        id="mention-suggested", hearing_id="hearing-1", article_url="https://example.test/a",
        source_name="Test Source", headline="Alex Dawson case update",
        match_status=MatchStatus.suggested_pending_review, match_confidence=MatchConfidence.medium,
        extracted_case_numbers=json.dumps([]), extracted_party_candidates=json.dumps(["Alex Dawson"]),
        match_signals=json.dumps({"name_match_score": 0.7}),
    )
    unmatched = NewsMention(
        id="mention-unmatched", article_url="https://example.test/b", source_name="Test Source",
        headline="Former deputy pleads guilty", match_status=MatchStatus.unmatched_review,
        extracted_case_numbers=json.dumps([]), extracted_party_candidates=json.dumps([]),
        match_signals=json.dumps({"court_relevance": True}),
    )
    discarded = NewsMention(
        id="mention-discarded", article_url="https://example.test/c", source_name="Test Source",
        headline="Garden feeds dozens", match_status=MatchStatus.discarded,
        extracted_case_numbers=json.dumps([]), extracted_party_candidates=json.dumps([]),
        match_signals=json.dumps({"court_relevance": False}),
    )
    seed.add_all([hearing, editor, suggested, unmatched, discarded])
    seed.commit()
    seed.close()

    yield TestClient(app), TestSession
    app.dependency_overrides.clear()


def _auth(client):
    r = client.post("/api/admin/login", json={"email": "editor@test.local", "password": "pw"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_queue_includes_suggested_and_unmatched_but_not_discarded(ctx):
    client, _Session = ctx
    r = client.get("/api/admin/review-queue/news-mentions", headers=_auth(client))
    assert r.status_code == 200
    ids = [m["id"] for m in r.json()]
    assert "mention-suggested" in ids
    assert "mention-unmatched" in ids
    assert "mention-discarded" not in ids


def test_suggested_items_come_first_and_carry_the_candidate_hearing(ctx):
    client, _Session = ctx
    body = client.get("/api/admin/review-queue/news-mentions", headers=_auth(client)).json()
    assert body[0]["id"] == "mention-suggested"
    assert body[0]["suggested_hearing"]["case_number"] == "2026CR000123"
    assert body[1]["suggested_hearing"] is None


def test_diagnosis_fields_are_exposed(ctx):
    client, _Session = ctx
    body = client.get("/api/admin/review-queue/news-mentions", headers=_auth(client)).json()
    suggested = next(m for m in body if m["id"] == "mention-suggested")
    assert suggested["extracted_party_candidates"] == ["Alex Dawson"]
    assert suggested["match_confidence"] == "medium"
    assert suggested["match_signals"]["name_match_score"] == 0.7


def test_count_matches_the_queue_length(ctx):
    client, _Session = ctx
    count = client.get("/api/admin/review-queue/news-mentions/count", headers=_auth(client)).json()["count"]
    queue = client.get("/api/admin/review-queue/news-mentions", headers=_auth(client)).json()
    assert count == len(queue) == 2


def test_confirm_suggested_mention(ctx, Session=None):
    client, Session = ctx
    r = client.post("/api/admin/news-mentions/mention-suggested/confirm", headers=_auth(client))
    assert r.status_code == 200
    assert r.json()["match_status"] == "manually_linked"

    db = Session()
    m = db.query(NewsMention).filter(NewsMention.id == "mention-suggested").first()
    assert m.match_status == MatchStatus.manually_linked
    assert m.hearing_id == "hearing-1"
    db.close()


def test_reject_suggested_mention_demotes_to_unmatched_and_clears_hearing(ctx):
    client, Session = ctx
    r = client.post("/api/admin/news-mentions/mention-suggested/reject", headers=_auth(client))
    assert r.status_code == 200
    assert r.json()["match_status"] == "unmatched_review"
    assert r.json()["suggested_hearing"] is None

    db = Session()
    m = db.query(NewsMention).filter(NewsMention.id == "mention-suggested").first()
    assert m.match_status == MatchStatus.unmatched_review
    assert m.hearing_id is None
    db.close()


def test_cannot_confirm_or_reject_an_already_unmatched_mention(ctx):
    client, _Session = ctx
    headers = _auth(client)
    assert client.post("/api/admin/news-mentions/mention-unmatched/confirm", headers=headers).status_code == 400
    assert client.post("/api/admin/news-mentions/mention-unmatched/reject", headers=headers).status_code == 400


def test_link_by_case_number(ctx):
    client, Session = ctx
    r = client.post("/api/admin/news-mentions/mention-unmatched/link",
                     json={"case_number": "2026CR000123"}, headers=_auth(client))
    assert r.status_code == 200, r.text
    assert r.json()["match_status"] == "manually_linked"

    db = Session()
    m = db.query(NewsMention).filter(NewsMention.id == "mention-unmatched").first()
    assert m.hearing_id == "hearing-1"
    db.close()


def test_link_by_case_number_404s_for_unknown_case(ctx):
    client, _Session = ctx
    r = client.post("/api/admin/news-mentions/mention-unmatched/link",
                     json={"case_number": "2026CR999999"}, headers=_auth(client))
    assert r.status_code == 404


def test_link_requires_exactly_one_of_hearing_id_or_case_number(ctx):
    client, _Session = ctx
    headers = _auth(client)
    neither = client.post("/api/admin/news-mentions/mention-unmatched/link", json={}, headers=headers)
    assert neither.status_code == 400
    both = client.post(
        "/api/admin/news-mentions/mention-unmatched/link",
        json={"hearing_id": "hearing-1", "case_number": "2026CR000123"}, headers=headers,
    )
    assert both.status_code == 400


def test_link_by_hearing_id_still_works(ctx):
    client, _Session = ctx
    r = client.post("/api/admin/news-mentions/mention-unmatched/link",
                     json={"hearing_id": "hearing-1"}, headers=_auth(client))
    assert r.status_code == 200
    assert r.json()["match_status"] == "manually_linked"


def test_backfill_rematch_endpoint_discards_the_noise_row(ctx):
    client, Session = ctx
    r = client.post("/api/admin/news-mentions/backfill-rematch", headers=_auth(client))
    assert r.status_code == 200, r.text
    body = r.json()
    # mention-unmatched's headline ("Former deputy pleads guilty") reads
    # as court-relevant, so it should survive; mention-discarded was
    # already terminal and untouched (checked stays 2: suggested + unmatched).
    assert body["checked"] == 2
    assert body["discarded"] == 0

    db = Session()
    still_there = db.query(NewsMention).filter(NewsMention.id == "mention-unmatched").first()
    assert still_there.match_status == MatchStatus.unmatched_review
    db.close()


def test_backfill_rematch_requires_editor(ctx):
    client, Session = ctx
    db = Session()
    db.add(AdminUser(email="contributor@test.local", hashed_password=hash_password("pw"),
                      role=AdminRole.contributor))
    db.commit()
    db.close()
    login = client.post("/api/admin/login", json={"email": "contributor@test.local", "password": "pw"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    r = client.post("/api/admin/news-mentions/backfill-rematch", headers=headers)
    assert r.status_code == 403


def test_discard_endpoint_still_deletes_the_row_outright(ctx):
    client, Session = ctx
    r = client.delete("/api/admin/news-mentions/mention-unmatched", headers=_auth(client))
    assert r.status_code == 200
    db = Session()
    assert db.query(NewsMention).filter(NewsMention.id == "mention-unmatched").first() is None
    db.close()

"""
Phase 8 doc: the admin review queue is now just the Tier 2 "weekly
reading list" -- confirm (relevance) / dismiss, no more confidence
tiers, no more "link by case number" (every row already has its
hearing_id), no more backfill-rematch (no fuzzy logic left to re-run).
Same ctx/TestClient fixture style as the file this replaces.
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
    MatchStatus,
    NewsMention,
    SourceType,
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
        case_category=CaseCategory.criminal, party_names='["ALEX DAWSON"]',
        hearing_type_raw="Jury Trial", hearing_type_display="Jury Trial",
        hearing_type_category=HearingTypeCategory.jury_trial.value, date=date(2026, 10, 1),
        court_location=CourtLocation.boulder_county, appearance_type=AppearanceType.in_person,
        status=HearingStatus.scheduled,
    )
    editor = AdminUser(email="editor@test.local", hashed_password=hash_password("pw"), role=AdminRole.editor)

    reading_list_item = NewsMention(
        id="mention-reading-list", hearing_id="hearing-1", article_url="https://example.test/a",
        source_name="example.test", headline="Alex Dawson case update",
        match_status=MatchStatus.in_weekly_reading_list, source_type=SourceType.search_result_general,
    )
    auto_matched = NewsMention(
        id="mention-auto", hearing_id="hearing-1", article_url="https://example.test/b",
        source_name="example.test", headline="Dawson trial begins, case 2026CR000123",
        match_status=MatchStatus.auto_matched, source_type=SourceType.search_result_case_number,
    )
    seed.add_all([hearing, editor, reading_list_item, auto_matched])
    seed.commit()
    seed.close()

    yield TestClient(app), TestSession
    app.dependency_overrides.clear()


def _auth(client):
    r = client.post("/api/admin/login", json={"email": "editor@test.local", "password": "pw"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_queue_includes_only_reading_list_items(ctx):
    client, _Session = ctx
    r = client.get("/api/admin/review-queue/news-mentions", headers=_auth(client))
    assert r.status_code == 200
    ids = [m["id"] for m in r.json()]
    assert ids == ["mention-reading-list"]


def test_queue_items_carry_their_hearing_context(ctx):
    client, _Session = ctx
    body = client.get("/api/admin/review-queue/news-mentions", headers=_auth(client)).json()
    assert body[0]["hearing"]["case_number"] == "2026CR000123"
    assert body[0]["hearing"]["party_names"] == ["ALEX DAWSON"]
    assert body[0]["source_type"] == "search_result_general"


def test_count_matches_the_queue_length(ctx):
    client, _Session = ctx
    count = client.get("/api/admin/review-queue/news-mentions/count", headers=_auth(client)).json()["count"]
    queue = client.get("/api/admin/review-queue/news-mentions", headers=_auth(client)).json()
    assert count == len(queue) == 1


def test_confirm_promotes_to_manually_linked(ctx):
    client, Session = ctx
    r = client.post("/api/admin/news-mentions/mention-reading-list/confirm", headers=_auth(client))
    assert r.status_code == 200
    assert r.json()["match_status"] == "manually_linked"

    db = Session()
    m = db.query(NewsMention).filter(NewsMention.id == "mention-reading-list").first()
    assert m.match_status == MatchStatus.manually_linked
    assert m.hearing_id == "hearing-1"  # unchanged -- confirm never touches which hearing it's linked to
    db.close()


def test_dismiss_sets_status_and_keeps_the_row(ctx):
    client, Session = ctx
    r = client.post("/api/admin/news-mentions/mention-reading-list/dismiss", headers=_auth(client))
    assert r.status_code == 200
    assert r.json()["match_status"] == "dismissed"

    db = Session()
    m = db.query(NewsMention).filter(NewsMention.id == "mention-reading-list").first()
    assert m is not None  # not deleted -- see app/routers/admin.py::dismiss_news_mention's docstring
    assert m.match_status == MatchStatus.dismissed
    db.close()


def test_cannot_confirm_or_dismiss_an_already_auto_matched_mention(ctx):
    client, _Session = ctx
    headers = _auth(client)
    assert client.post("/api/admin/news-mentions/mention-auto/confirm", headers=headers).status_code == 400
    assert client.post("/api/admin/news-mentions/mention-auto/dismiss", headers=headers).status_code == 400


def test_confirming_a_nonexistent_mention_404s(ctx):
    client, _Session = ctx
    r = client.post("/api/admin/news-mentions/does-not-exist/confirm", headers=_auth(client))
    assert r.status_code == 404


def test_auto_matched_list_returns_only_auto_matched_rows(ctx):
    client, _Session = ctx
    r = client.get("/api/admin/news-mentions/auto-matched", headers=_auth(client))
    assert r.status_code == 200
    ids = [m["id"] for m in r.json()]
    assert ids == ["mention-auto"]


def test_public_hearing_endpoint_embeds_only_confirmed_news_mentions(ctx):
    """Regression test for a real crash caught in local manual testing:
    GET /api/hearings/{id} 500'd on any hearing with a news mention,
    because NewsMentionOut.hearing reads NewsMention.hearing (an ORM
    relationship, i.e. a raw Hearing object) and NewsMentionHearingSummaryOut
    needs its own from_attributes=True to accept that -- having it only on
    the outer NewsMentionOut isn't enough. Also confirms the
    HearingOut._only_confirmed_news validator does its job: the
    in_weekly_reading_list row must never reach the public API."""
    client, _Session = ctx
    r = client.get("/api/hearings/hearing-1")
    assert r.status_code == 200
    ids = [m["id"] for m in r.json()["news_mentions"]]
    assert ids == ["mention-auto"]


def test_old_link_and_reject_and_backfill_endpoints_are_gone(ctx):
    client, _Session = ctx
    headers = _auth(client)
    assert client.post("/api/admin/news-mentions/mention-reading-list/link",
                        json={"case_number": "2026CR000123"}, headers=headers).status_code == 404
    assert client.post("/api/admin/news-mentions/mention-reading-list/reject", headers=headers).status_code == 404
    assert client.post("/api/admin/news-mentions/backfill-rematch", headers=headers).status_code == 404

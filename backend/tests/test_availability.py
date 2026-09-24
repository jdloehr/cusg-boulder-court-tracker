"""
Phase-6.2 doc, Sections 4 and 6: the Justice-only recurring-availability
meter and the matching newsletter opt-in. Covers:
- app/availability.py's pure functions (time/duration parsing, overlap).
- The Justice-only /me/availability endpoints and the batched
  /hearings/availability-summary meter endpoint, including that it's
  gated to real Justices and never leaks into the public JusticeOut shape.
- The digest job's new personal_availability branch.
- SubscriptionCreate's availability_blocks validation.
"""
import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.availability import (
    hearing_matches_blocks,
    parse_duration_minutes,
    parse_hearing_time,
    weekday_abbr,
)
from app.db import get_db
from app.jobs.digest import hearings_matching_subscription
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
    Subscription,
    SubscriptionFilterType,
    SubscriptionFrequency,
)
from app.rate_limit import reset_for_tests

# --- Pure-function tests: no DB/client needed ------------------------------


def test_parse_hearing_time_handles_the_formats_seen_in_real_docket_data():
    assert parse_hearing_time("9:00 AM") == 9 * 60
    assert parse_hearing_time("1:30 PM") == 13 * 60 + 30
    assert parse_hearing_time("14:00") == 14 * 60
    assert parse_hearing_time("") is None
    assert parse_hearing_time(None) is None
    assert parse_hearing_time("not a time") is None


def test_parse_duration_minutes_matches_real_fixture_values():
    assert parse_duration_minutes("2 hours") == 120
    assert parse_duration_minutes("30 minutes") == 30
    assert parse_duration_minutes("1 hour") == 60
    assert parse_duration_minutes("45 minutes") == 45
    assert parse_duration_minutes("1 day") == 24 * 60
    assert parse_duration_minutes("1 hour 30 minutes") == 90


def test_parse_duration_minutes_falls_back_to_the_documented_default():
    assert parse_duration_minutes(None) == 60
    assert parse_duration_minutes("") == 60
    assert parse_duration_minutes("unknown") == 60


def test_weekday_abbr_matches_python_date_weekday():
    assert weekday_abbr(date(2026, 9, 21)) == "mon"  # a known Monday
    assert weekday_abbr(date(2026, 9, 27)) == "sun"


def test_hearing_matches_blocks_requires_same_day_and_overlap():
    blocks = [{"day_of_week": "mon", "start_time": "09:00", "end_time": "12:00"}]
    # Monday, 9am, 1 hour -- inside the block.
    assert hearing_matches_blocks(date(2026, 9, 21), "9:00 AM", "1 hour", blocks) is True
    # Monday, but starts after the block ends.
    assert hearing_matches_blocks(date(2026, 9, 21), "1:00 PM", "1 hour", blocks) is False
    # Tuesday -- wrong day entirely.
    assert hearing_matches_blocks(date(2026, 9, 22), "9:00 AM", "1 hour", blocks) is False
    # Partial overlap still counts ("full-duration overlap not required").
    assert hearing_matches_blocks(date(2026, 9, 21), "11:30 AM", "2 hours", blocks) is True


def test_hearing_matches_blocks_never_matches_an_unparseable_time():
    blocks = [{"day_of_week": "mon", "start_time": "09:00", "end_time": "12:00"}]
    assert hearing_matches_blocks(date(2026, 9, 21), "", "1 hour", blocks) is False
    assert hearing_matches_blocks(date(2026, 9, 21), None, "1 hour", blocks) is False


# --- Endpoint tests ----------------------------------------------------------


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
    # Relative to today, not hardcoded -- default_upcoming_hearings only
    # looks at the next 14 days, and a fixed past date would silently drop
    # out of every query as real time passes (the exact bug fixed in
    # test_hearing_sorting.py/test_docket_pull.py during Phase 6).
    first_date = date.today() + timedelta(days=1)
    second_date = first_date + timedelta(days=1)
    hearing_a = Hearing(
        id="hearing-a", source=HearingSource.state_docket_export, case_number="2026CR000123",
        case_category=CaseCategory.criminal, hearing_type_raw="Jury Trial", hearing_type_display="Jury Trial",
        hearing_type_category=HearingTypeCategory.jury_trial.value, date=first_date, time="9:00 AM",
        duration="2 hours", court_location=CourtLocation.boulder_county,
        appearance_type=AppearanceType.in_person, status=HearingStatus.scheduled,
    )
    hearing_b = Hearing(
        id="hearing-b", source=HearingSource.state_docket_export, case_number="2026CR000456",
        case_category=CaseCategory.criminal, hearing_type_raw="Motions Hearing", hearing_type_display="Motions Hearing",
        hearing_type_category=HearingTypeCategory.other.value, date=second_date, time="1:00 PM",
        duration="1 hour", court_location=CourtLocation.boulder_county,
        appearance_type=AppearanceType.in_person, status=HearingStatus.scheduled,
    )
    dillon = AdminUser(email="dillon@test.local", hashed_password=hash_password("pw"),
                        is_justice=True, is_active=True, display_name="Dillon Rankin")
    joshua = AdminUser(email="joshua@test.local", hashed_password=hash_password("pw"),
                        is_justice=True, is_active=True, display_name="Joshua Loehr")
    non_justice = AdminUser(email="editor@test.local", hashed_password=hash_password("pw"), role=None)
    seed.add_all([hearing_a, hearing_b, dillon, joshua, non_justice])
    seed.commit()
    seed.close()

    yield TestClient(app)
    app.dependency_overrides.clear()


def _first_hearing_day_abbr() -> str:
    return weekday_abbr(date.today() + timedelta(days=1))


def _auth(client, email):
    r = client.post("/api/admin/login", json={"email": email, "password": "pw"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_availability_endpoints_require_a_justice_login(client):
    r = client.get("/api/justices/me/availability")
    assert r.status_code == 401

    non_justice_headers = _auth(client, "editor@test.local")
    r2 = client.get("/api/justices/me/availability", headers=non_justice_headers)
    assert r2.status_code == 403


def test_a_justice_can_set_and_read_back_their_own_availability(client):
    headers = _auth(client, "dillon@test.local")
    blocks = [{"day_of_week": "mon", "start_time": "09:00", "end_time": "12:00"}]

    r = client.patch("/api/justices/me/availability", json={"blocks": blocks}, headers=headers)
    assert r.status_code == 200
    assert r.json()["blocks"] == blocks

    r2 = client.get("/api/justices/me/availability", headers=headers)
    assert r2.json()["blocks"] == blocks


def test_updating_availability_is_a_full_replace_not_incremental(client):
    headers = _auth(client, "dillon@test.local")
    client.patch("/api/justices/me/availability",
                  json={"blocks": [{"day_of_week": "mon", "start_time": "09:00", "end_time": "12:00"}]},
                  headers=headers)
    r = client.patch("/api/justices/me/availability",
                      json={"blocks": [{"day_of_week": "wed", "start_time": "14:00", "end_time": "16:00"}]},
                      headers=headers)
    assert r.json()["blocks"] == [{"day_of_week": "wed", "start_time": "14:00", "end_time": "16:00"}]


def test_availability_never_appears_on_the_public_justice_endpoints(client):
    headers = _auth(client, "dillon@test.local")
    client.patch("/api/justices/me/availability",
                  json={"blocks": [{"day_of_week": "mon", "start_time": "09:00", "end_time": "12:00"}]},
                  headers=headers)

    roster = client.get("/api/justices").json()
    dillon_row = next(j for j in roster if j["display_name"] == "Dillon Rankin")
    assert "availability_blocks" not in dillon_row
    assert "availability" not in dillon_row

    profile = client.get(f"/api/justices/{dillon_row['id']}").json()
    assert "availability_blocks" not in profile
    assert "availability" not in profile


def test_availability_summary_requires_a_justice_login(client):
    r = client.post("/api/hearings/availability-summary", json={"hearing_ids": ["hearing-a"]})
    assert r.status_code == 401

    non_justice_headers = _auth(client, "editor@test.local")
    r2 = client.post("/api/hearings/availability-summary", json={"hearing_ids": ["hearing-a"]},
                      headers=non_justice_headers)
    assert r2.status_code == 403


def test_availability_summary_computes_free_count_and_names(client):
    dillon_headers = _auth(client, "dillon@test.local")
    joshua_headers = _auth(client, "joshua@test.local")
    client.patch("/api/justices/me/availability",
                  json={"blocks": [{"day_of_week": _first_hearing_day_abbr(), "start_time": "09:00", "end_time": "12:00"}]},
                  headers=dillon_headers)
    # Joshua has no availability set at all -- should count as not free anywhere.

    r = client.post("/api/hearings/availability-summary",
                     json={"hearing_ids": ["hearing-a", "hearing-b"]}, headers=joshua_headers)
    assert r.status_code == 200
    body = r.json()

    assert body["hearing-a"]["total"] == 2
    assert body["hearing-a"]["free_count"] == 1
    assert body["hearing-a"]["free_justice_names"] == ["Dillon Rankin"]
    assert body["hearing-a"]["time_known"] is True

    assert body["hearing-b"]["free_count"] == 0
    assert body["hearing-b"]["free_justice_names"] == []


def test_availability_summary_only_returns_requested_hearing_ids(client):
    headers = _auth(client, "dillon@test.local")
    r = client.post("/api/hearings/availability-summary", json={"hearing_ids": ["hearing-a"]}, headers=headers)
    assert set(r.json().keys()) == {"hearing-a"}


# --- Digest job's personal_availability branch ------------------------------


def test_digest_personal_availability_branch_filters_to_overlapping_hearings(client):
    # Reuse the same in-memory DB the fixture already wired up via the
    # dependency override, rather than standing up a second engine.
    gen = app.dependency_overrides[get_db]()
    db = next(gen)
    try:
        sub = Subscription(
            email="watcher@example.com",
            filter_type=SubscriptionFilterType.personal_availability,
            filter_value="n/a",
            frequency=SubscriptionFrequency.weekly_digest,
            availability_blocks=json.dumps(
                [{"day_of_week": _first_hearing_day_abbr(), "start_time": "09:00", "end_time": "12:00"}]
            ),
        )
        db.add(sub)
        db.commit()
        db.refresh(sub)

        matching = hearings_matching_subscription(db, sub)
        assert {h.id for h in matching} == {"hearing-a"}
    finally:
        gen.close()


# --- SubscriptionCreate's availability_blocks validation --------------------


def test_subscribing_with_personal_availability_requires_blocks(client):
    r = client.post("/api/subscriptions", json={
        "email": "watcher@example.com", "filter_type": "personal_availability",
        "filter_value": "n/a", "frequency": "weekly_digest",
    })
    assert r.status_code == 422


def test_subscribing_with_personal_availability_and_blocks_succeeds(client):
    blocks = [{"day_of_week": "mon", "start_time": "09:00", "end_time": "12:00"}]
    r = client.post("/api/subscriptions", json={
        "email": "watcher@example.com", "filter_type": "personal_availability",
        "filter_value": "n/a", "frequency": "weekly_digest", "availability_blocks": blocks,
    })
    assert r.status_code == 200, r.text
    assert r.json()["availability_blocks"] == blocks


def test_availability_blocks_rejected_for_a_non_personal_filter_type(client):
    r = client.post("/api/subscriptions", json={
        "email": "watcher@example.com", "filter_type": "hearing_type_category",
        "filter_value": "jury_trial", "frequency": "weekly_digest",
        "availability_blocks": [{"day_of_week": "mon", "start_time": "09:00", "end_time": "12:00"}],
    })
    assert r.status_code == 422

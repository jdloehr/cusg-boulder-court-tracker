"""
Phase-4 doc, Section 2.2: input validation/rate-limiting extended to
every public write path, not just the ones earlier phases already
covered.
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import (
    AppearanceType,
    Base,
    CaseCategory,
    CourtLocation,
    Hearing,
    HearingSource,
    HearingStatus,
    HearingTypeCategory,
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
    seed.add(Hearing(
        id="hearing-1", source=HearingSource.state_docket_export, case_number="2026CR000123",
        case_category=CaseCategory.criminal, hearing_type_raw="Jury Trial", hearing_type_display="Jury Trial",
        hearing_type_category=HearingTypeCategory.jury_trial.value, date=date(2026, 10, 1),
        court_location=CourtLocation.boulder_county, appearance_type=AppearanceType.in_person,
        status=HearingStatus.scheduled,
    ))
    seed.commit()
    seed.close()

    yield TestClient(app)
    app.dependency_overrides.clear()


# --- Email format validation --------------------------------------------------

@pytest.mark.parametrize("bad_email", ["not-an-email", "missing-at.example.com", "@example.com", "a@b"])
def test_subscription_rejects_malformed_email(client, bad_email):
    r = client.post("/api/subscriptions", json={
        "email": bad_email, "filter_type": "hearing_type_category",
        "filter_value": "jury_trial", "frequency": "weekly_digest",
    })
    assert r.status_code == 422


def test_subscription_accepts_a_well_formed_email(client):
    r = client.post("/api/subscriptions", json={
        "email": "student@colorado.edu", "filter_type": "hearing_type_category",
        "filter_value": "jury_trial", "frequency": "weekly_digest",
    })
    assert r.status_code == 200


def test_admin_login_rejects_malformed_email(client):
    r = client.post("/api/admin/login", json={"email": "not-an-email", "password": "whatever"})
    assert r.status_code == 422


# --- Subscription rate limiting -----------------------------------------------

def test_subscriptions_are_rate_limited(client):
    for i in range(10):
        r = client.post("/api/subscriptions", json={
            "email": f"student{i}@colorado.edu", "filter_type": "hearing_type_category",
            "filter_value": "jury_trial", "frequency": "weekly_digest",
        })
        assert r.status_code == 200
    blocked = client.post("/api/subscriptions", json={
        "email": "one-too-many@colorado.edu", "filter_type": "hearing_type_category",
        "filter_value": "jury_trial", "frequency": "weekly_digest",
    })
    assert blocked.status_code == 429


# --- Community "add case details" submissions ---------------------------------

def test_community_submission_is_rate_limited(client):
    for _ in range(5):
        r = client.post("/api/hearings/hearing-1/submissions", json={"judge_name": "Hon. Someone"})
        assert r.status_code == 201
    blocked = client.post("/api/hearings/hearing-1/submissions", json={"judge_name": "Hon. Someone Else"})
    assert blocked.status_code == 429


def test_community_submission_rejects_spam(client):
    r = client.post("/api/hearings/hearing-1/submissions", json={
        "summary_text": "this is total bullshit and a scam, click here http://spam.example http://spam2.example",
    })
    assert r.status_code == 400

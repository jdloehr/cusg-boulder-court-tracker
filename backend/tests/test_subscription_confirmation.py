"""
Oct 2026 review item 2: double opt-in for /api/subscriptions. A brand-
new subscription is created unconfirmed and gets no mail -- every
digest/alert query in app/jobs/digest.py filters on is_confirmed -- until
the emailed confirmation link is used.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_token
from app.db import get_db
from app.jobs import digest
from app.main import app
from app.models import Base, Subscription, SubscriptionFilterType, SubscriptionFrequency
from app.rate_limit import reset_for_tests
from app.routers import public as public_router


@pytest.fixture()
def client(monkeypatch):
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
    sent = []
    # routers/public.py did `from app.jobs.digest import send_email`, a
    # direct name-binding import -- patching app.jobs.digest.send_email
    # itself wouldn't touch public.py's own already-bound reference to
    # the original function, so the patch target has to be public.py's
    # copy of the name instead.
    fake_send = lambda to, subject, body, **kw: sent.append((to, subject, body))  # noqa: E731
    monkeypatch.setattr(public_router, "send_email", fake_send)
    monkeypatch.setattr(digest, "send_email", fake_send)
    yield TestClient(app), sent
    app.dependency_overrides.clear()


def test_new_subscription_is_unconfirmed_and_gets_a_confirmation_email(client):
    c, sent = client
    r = c.post("/api/subscriptions", json={
        "email": "watcher@example.com", "filter_type": "hearing_type_category",
        "filter_value": "jury_trial", "frequency": "weekly_digest",
    })
    assert r.status_code == 200, r.text
    assert r.json()["is_confirmed"] is False
    assert len(sent) == 1
    to, subject, body = sent[0]
    assert to == "watcher@example.com"
    assert "confirm" in subject.lower()
    assert "/subscriptions/confirm/" in body


def test_confirm_endpoint_flips_is_confirmed_and_is_single_use(client):
    c, sent = client
    c.post("/api/subscriptions", json={
        "email": "watcher@example.com", "filter_type": "hearing_type_category",
        "filter_value": "jury_trial", "frequency": "weekly_digest",
    })
    body = sent[0][2]
    token = body.rsplit("/", 1)[-1].strip()

    peek = c.get(f"/api/subscriptions/confirm/{token}")
    assert peek.status_code == 200
    assert peek.json()["email"] == "watcher@example.com"

    confirm = c.post(f"/api/subscriptions/confirm/{token}")
    assert confirm.status_code == 200
    assert confirm.json() == {"status": "confirmed"}

    # Same token again -- already cleared, so this looks exactly like an
    # unknown/invalid token, not a distinct "already used" leak.
    again = c.post(f"/api/subscriptions/confirm/{token}")
    assert again.status_code == 404


def test_confirm_endpoint_404s_for_unknown_token(client):
    c, _sent = client
    assert c.get("/api/subscriptions/confirm/not-a-real-token").status_code == 404
    assert c.post("/api/subscriptions/confirm/not-a-real-token").status_code == 404


def test_resubmitting_unconfirmed_subscription_resends_a_fresh_token(client):
    c, sent = client
    payload = {
        "email": "watcher@example.com", "filter_type": "hearing_type_category",
        "filter_value": "jury_trial", "frequency": "weekly_digest",
    }
    r1 = c.post("/api/subscriptions", json=payload)
    r2 = c.post("/api/subscriptions", json=payload)
    assert r1.json()["id"] == r2.json()["id"]  # still the same row, not a duplicate
    assert len(sent) == 2  # confirmation re-sent

    first_token = sent[0][2].rsplit("/", 1)[-1].strip()
    second_token = sent[1][2].rsplit("/", 1)[-1].strip()
    assert first_token != second_token

    # The old link from the first email no longer works.
    assert c.get(f"/api/subscriptions/confirm/{first_token}").status_code == 404
    # The new one does.
    assert c.get(f"/api/subscriptions/confirm/{second_token}").status_code == 200


def test_resubmitting_an_already_confirmed_subscription_does_not_resend(client):
    c, sent = client
    payload = {
        "email": "watcher@example.com", "filter_type": "hearing_type_category",
        "filter_value": "jury_trial", "frequency": "weekly_digest",
    }
    c.post("/api/subscriptions", json=payload)
    token = sent[0][2].rsplit("/", 1)[-1].strip()
    c.post(f"/api/subscriptions/confirm/{token}")

    r2 = c.post("/api/subscriptions", json=payload)
    assert r2.json()["is_confirmed"] is True
    assert len(sent) == 1  # no second confirmation email


def test_weekly_digest_skips_unconfirmed_subscriptions(client):
    c, sent = client
    db = next(app.dependency_overrides[get_db]())
    try:
        db.add(Subscription(
            email="unconfirmed@example.com", filter_type=SubscriptionFilterType.hearing_type_category,
            filter_value="jury_trial", frequency=SubscriptionFrequency.weekly_digest,
            unsubscribe_token="tok-a", is_confirmed=False, confirmation_token_hash=hash_token("whatever"),
        ))
        db.add(Subscription(
            email="confirmed@example.com", filter_type=SubscriptionFilterType.hearing_type_category,
            filter_value="jury_trial", frequency=SubscriptionFrequency.weekly_digest,
            unsubscribe_token="tok-b", is_confirmed=True,
        ))
        db.commit()
        summary = digest.run_weekly_digest(db)
    finally:
        db.close()

    assert summary.subscriptions_processed == 1
    assert [to for to, *_ in sent] == ["confirmed@example.com"]

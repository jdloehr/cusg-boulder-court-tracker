"""
Phase-2 doc, Section 1: last-updated timestamp + manual refresh with a
global cooldown. TestClient-based since the cooldown check happens in the
router, not something worth reaching into directly.
"""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import Base, JobRun
from app.rate_limit import reset_for_tests


@pytest.fixture()
def client_factory():
    reset_for_tests()  # each test gets a fresh per-IP rate-limit budget
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
    db = TestSession()
    yield TestClient(app), db
    db.close()
    app.dependency_overrides.clear()


def test_data_status_with_no_job_runs_yet(client_factory):
    client, _db = client_factory
    r = client.get("/api/data-status")
    assert r.status_code == 200
    body = r.json()
    assert body["last_updated_at"] is None
    assert body["next_refresh_available_at"] is None
    assert body["refresh_cooldown_minutes"] == 20


def test_data_status_reflects_last_successful_run(client_factory):
    client, db = client_factory
    now = datetime.utcnow()
    db.add(JobRun(job_name="docket_pull", started_at=now - timedelta(minutes=30),
                   finished_at=now - timedelta(minutes=29), success=True, rows_seen=5000, rows_upserted=5000))
    db.commit()

    body = client.get("/api/data-status").json()
    assert body["last_updated_at"] is not None
    # cooldown window (from the run's start) has already elapsed
    assert body["next_refresh_available_at"] is not None


def test_refresh_rejected_during_cooldown(client_factory):
    client, db = client_factory
    now = datetime.utcnow()
    db.add(JobRun(job_name="docket_pull", started_at=now - timedelta(minutes=2), success=True))
    db.commit()

    r = client.post("/api/refresh")
    assert r.status_code == 429
    assert "Try again after" in r.json()["detail"]


def test_refresh_allowed_after_cooldown_elapses(client_factory, monkeypatch):
    client, db = client_factory
    now = datetime.utcnow()
    db.add(JobRun(job_name="docket_pull", started_at=now - timedelta(minutes=25), success=True))
    db.commit()

    # Don't actually hit the live docket export in a unit test -- just
    # confirm the cooldown check lets the request through and schedules
    # the background task rather than rejecting with 429.
    monkeypatch.setattr("app.routers.public._run_refresh_in_background", lambda: None)
    r = client.post("/api/refresh")
    assert r.status_code == 202


def test_refresh_allowed_when_never_run_before(client_factory, monkeypatch):
    client, _db = client_factory
    monkeypatch.setattr("app.routers.public._run_refresh_in_background", lambda: None)
    r = client.post("/api/refresh")
    assert r.status_code == 202

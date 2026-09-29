"""
Phase 8 doc: daily quota tracking for the search API, and the
exactly-once-per-day alert threshold.
"""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.external_api_usage import record_usage
from app.models import Base, ExternalApiUsage


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_record_usage_creates_a_row_on_first_call(db):
    now = datetime(2026, 9, 29, 12, 0, 0)
    row = record_usage(db, "google_custom_search", now)
    assert row.query_count == 1
    assert row.usage_date == date(2026, 9, 29)


def test_record_usage_increments_on_subsequent_calls_same_day(db):
    now = datetime(2026, 9, 29, 12, 0, 0)
    record_usage(db, "google_custom_search", now)
    record_usage(db, "google_custom_search", now.replace(hour=13))
    row = db.query(ExternalApiUsage).filter_by(api_name="google_custom_search", usage_date=date(2026, 9, 29)).one()
    assert row.query_count == 2


def test_record_usage_uses_a_separate_row_for_a_separate_date(db):
    day1 = datetime(2026, 9, 29, 12, 0, 0)
    day2 = day1 + timedelta(days=1)
    record_usage(db, "google_custom_search", day1)
    record_usage(db, "google_custom_search", day2)
    rows = db.query(ExternalApiUsage).filter_by(api_name="google_custom_search").all()
    assert len(rows) == 2
    assert {r.query_count for r in rows} == {1, 1}


def test_alert_fires_exactly_once_when_crossing_the_threshold(db, monkeypatch):
    alerts = []
    monkeypatch.setattr("app.external_api_usage.alert_quota_warning", lambda *a, **k: alerts.append((a, k)))
    monkeypatch.setattr("app.external_api_usage.SEARCH_API_ALERT_THRESHOLD", 3)

    now = datetime(2026, 9, 29, 12, 0, 0)
    for _ in range(5):
        record_usage(db, "google_custom_search", now)

    assert len(alerts) == 1


def test_alert_does_not_fire_below_the_threshold(db, monkeypatch):
    alerts = []
    monkeypatch.setattr("app.external_api_usage.alert_quota_warning", lambda *a, **k: alerts.append((a, k)))
    monkeypatch.setattr("app.external_api_usage.SEARCH_API_ALERT_THRESHOLD", 10)

    now = datetime(2026, 9, 29, 12, 0, 0)
    for _ in range(5):
        record_usage(db, "google_custom_search", now)

    assert len(alerts) == 0


def test_a_new_days_row_does_not_inherit_the_previous_days_alert_sent_at(db, monkeypatch):
    alerts = []
    monkeypatch.setattr("app.external_api_usage.alert_quota_warning", lambda *a, **k: alerts.append((a, k)))
    monkeypatch.setattr("app.external_api_usage.SEARCH_API_ALERT_THRESHOLD", 2)

    day1 = datetime(2026, 9, 29, 12, 0, 0)
    day2 = day1 + timedelta(days=1)
    record_usage(db, "google_custom_search", day1)
    record_usage(db, "google_custom_search", day1)  # crosses threshold on day 1
    assert len(alerts) == 1

    record_usage(db, "google_custom_search", day2)
    record_usage(db, "google_custom_search", day2)  # crosses threshold again, but on a fresh day
    assert len(alerts) == 2

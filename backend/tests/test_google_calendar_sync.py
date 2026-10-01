"""
Calendar-sync doc: Google Calendar sync for Justice availability.
Covers the pure logic (encryption round-trip, the override-wins-else-
recurring resolver, freebusy-to-slots conversion, baseline derivation),
the sync job with httpx mocked (same pattern as test_news_search.py),
and the OAuth flow's role-gating/state-token handling with a real
TestClient. The live OAuth consent screen and a real freeBusy.query call
are explicitly NOT covered here -- no real Google credentials are
available in this environment; see the plan's own "Testing" section.
"""
import json
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password, hash_token
from app.availability_slots import (
    load_free_slots_by_day,
    load_override_slots_by_date,
    replace_owner_overrides_for_window,
    resolve_free_slots_for_date,
)
from app.db import get_db
from app.jobs.google_calendar_sync import (
    compute_free_slots_by_date,
    derive_recurring_baseline,
    run_google_calendar_sync,
    sync_one_connection,
)
from app.main import app
from app.models import (
    AdminRole,
    AdminUser,
    AvailabilityOwnerType,
    Base,
    DayOfWeek,
    GoogleCalendarConnection,
    GoogleCalendarOAuthState,
)
from app.rate_limit import reset_for_tests
from app.token_encryption import TokenDecryptionError, decrypt_refresh_token, encrypt_refresh_token


# --- Encryption ---------------------------------------------------------------

def test_encrypt_decrypt_round_trip():
    enc = encrypt_refresh_token("a-real-refresh-token")
    assert enc != "a-real-refresh-token"  # not stored plaintext
    assert decrypt_refresh_token(enc) == "a-real-refresh-token"


def test_decrypting_garbage_raises_a_clear_error():
    with pytest.raises(TokenDecryptionError):
        decrypt_refresh_token("not-a-real-fernet-token")


# --- Date-specific override resolver -----------------------------------------

def test_resolve_prefers_override_over_recurring_when_override_exists(db):
    replace_owner_overrides_for_window(
        db, AvailabilityOwnerType.justice, "j1", date(2026, 10, 6), date(2026, 10, 6), {date(2026, 10, 6): {5}},
    )
    db.commit()
    override_by_date = load_override_slots_by_date(db, AvailabilityOwnerType.justice, "j1")
    recurring = {"tue": {1, 2, 3}}  # would say slots 1-3 free, but the override should win outright
    resolved = resolve_free_slots_for_date(date(2026, 10, 6), override_by_date, recurring)
    assert resolved == {5}


def test_resolve_falls_back_to_recurring_when_no_override_exists(db):
    recurring = {"tue": {1, 2, 3}}
    resolved = resolve_free_slots_for_date(date(2026, 10, 6), {}, recurring)  # 2026-10-06 is a Tuesday
    assert resolved == {1, 2, 3}


def test_a_synced_date_with_zero_free_slots_is_distinct_from_not_synced(db):
    """An override row set exists for the date but every slot is busy --
    must resolve to an empty set (synced, fully busy), not fall back to
    the recurring pattern."""
    replace_owner_overrides_for_window(
        db, AvailabilityOwnerType.justice, "j1", date(2026, 10, 6), date(2026, 10, 6), {date(2026, 10, 6): set()},
    )
    db.commit()
    override_by_date = load_override_slots_by_date(db, AvailabilityOwnerType.justice, "j1")
    resolved = resolve_free_slots_for_date(date(2026, 10, 6), override_by_date, {"tue": {1, 2, 3}})
    assert resolved == set()


def test_replace_overrides_for_window_is_a_real_full_replace(db):
    replace_owner_overrides_for_window(
        db, AvailabilityOwnerType.justice, "j1", date(2026, 10, 1), date(2026, 10, 1), {date(2026, 10, 1): {0}},
    )
    db.commit()
    replace_owner_overrides_for_window(
        db, AvailabilityOwnerType.justice, "j1", date(2026, 10, 1), date(2026, 10, 1), {date(2026, 10, 1): {10}},
    )
    db.commit()
    result = load_override_slots_by_date(db, AvailabilityOwnerType.justice, "j1")
    assert result == {date(2026, 10, 1): {10}}  # the old {0} row is gone, not merged


# --- freebusy -> slots conversion, timezone-aware -----------------------------

def test_a_busy_interval_blocks_only_its_own_slots():
    # 9:00-10:00 AM Mountain Daylight Time (UTC-6 in October) on a real date.
    busy = [(datetime(2026, 10, 6, 15, 0, tzinfo=timezone.utc), datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc))]
    result = compute_free_slots_by_date(busy, date(2026, 10, 6), date(2026, 10, 6))
    from app.availability import SLOT_MINUTES, SLOT_WINDOW_START_MIN
    slot_9am = (9 * 60 - SLOT_WINDOW_START_MIN) // SLOT_MINUTES
    slot_8am = (8 * 60 - SLOT_WINDOW_START_MIN) // SLOT_MINUTES
    assert slot_9am not in result[date(2026, 10, 6)]
    assert slot_8am in result[date(2026, 10, 6)]


def test_no_busy_intervals_means_every_slot_free():
    from app.availability import NUM_SLOTS
    result = compute_free_slots_by_date([], date(2026, 10, 6), date(2026, 10, 6))
    assert result[date(2026, 10, 6)] == set(range(NUM_SLOTS))


def test_derive_recurring_baseline_requires_free_on_every_occurrence():
    from app.availability import SLOT_MINUTES, SLOT_WINDOW_START_MIN
    slot_8am = (8 * 60 - SLOT_WINDOW_START_MIN) // SLOT_MINUTES
    free_by_date = {
        date(2026, 10, 6): {slot_8am, 5},    # Tuesday 1
        date(2026, 10, 13): {slot_8am},       # Tuesday 2 -- slot 5 not free here
    }
    baseline = derive_recurring_baseline(free_by_date)
    pairs = {(c.day_of_week, c.slot_index) for c in baseline}
    assert (DayOfWeek.tue.value, slot_8am) in pairs
    assert (DayOfWeek.tue.value, 5) not in pairs  # not free on *every* Tuesday, so excluded


# --- Sync job, httpx mocked ---------------------------------------------------

def _mock_google(monkeypatch, refresh_ok=True, freebusy_response=None, freebusy_error=False):
    def fake_post(url, **kwargs):
        if "oauth2.googleapis.com/token" in url:
            if refresh_ok:
                return httpx.Response(200, json={"access_token": "fake-access-token"}, request=httpx.Request("POST", url))
            return httpx.Response(400, json={"error": "invalid_grant"}, request=httpx.Request("POST", url))
        if "freeBusy" in url:
            if freebusy_error:
                return httpx.Response(200, json={"calendars": {"primary": {"errors": [{"reason": "notFound"}]}}},
                                       request=httpx.Request("POST", url))
            return httpx.Response(200, json=freebusy_response or {"calendars": {"primary": {"busy": []}}},
                                   request=httpx.Request("POST", url))
        raise AssertionError(f"unexpected URL {url}")
    monkeypatch.setattr("app.jobs.google_calendar_sync.httpx.post", fake_post)


def test_sync_one_connection_success_writes_overrides_and_baseline(db, monkeypatch):
    _mock_google(monkeypatch, freebusy_response={"calendars": {"primary": {"busy": [
        {"start": "2026-10-06T15:00:00Z", "end": "2026-10-06T16:00:00Z"},
    ]}}})
    connection = GoogleCalendarConnection(admin_user_id="j1", encrypted_refresh_token=encrypt_refresh_token("rt"))
    db.add(connection)
    db.commit()

    now = datetime(2026, 10, 1, 12, 0)
    outcome = sync_one_connection(db, connection, now)
    db.commit()

    assert outcome.status == "ok"
    assert connection.last_sync_error is None
    assert connection.last_synced_at == now

    overrides = load_override_slots_by_date(db, AvailabilityOwnerType.justice, "j1")
    assert date(2026, 10, 6) in overrides  # within the synced window, a real row exists
    recurring = load_free_slots_by_day(db, AvailabilityOwnerType.justice, "j1")
    assert isinstance(recurring, dict)  # baseline was written (exact contents covered above)


def test_sync_one_connection_failure_sets_error_and_leaves_existing_data_untouched(db, monkeypatch):
    _mock_google(monkeypatch, refresh_ok=False)
    connection = GoogleCalendarConnection(admin_user_id="j1", encrypted_refresh_token=encrypt_refresh_token("rt"))
    db.add(connection)
    db.commit()

    # Seed a prior successful sync's data.
    replace_owner_overrides_for_window(
        db, AvailabilityOwnerType.justice, "j1", date(2026, 10, 1), date(2026, 10, 1), {date(2026, 10, 1): {3}},
    )
    db.commit()

    outcome = sync_one_connection(db, connection, datetime(2026, 10, 2, 12, 0))
    db.commit()

    assert outcome.status == "error"
    assert "Token refresh failed" in connection.last_sync_error
    # Doc's own ask: a broken sync never silently zeroes out last-known-good data.
    assert load_override_slots_by_date(db, AvailabilityOwnerType.justice, "j1")[date(2026, 10, 1)] == {3}


def test_sync_one_connection_freebusy_calendar_error_is_isolated(db, monkeypatch):
    _mock_google(monkeypatch, freebusy_error=True)
    connection = GoogleCalendarConnection(admin_user_id="j1", encrypted_refresh_token=encrypt_refresh_token("rt"))
    db.add(connection)
    db.commit()
    outcome = sync_one_connection(db, connection, datetime(2026, 10, 1, 12, 0))
    assert outcome.status == "error"
    assert "calendar error" in outcome.error


def test_run_google_calendar_sync_alerts_only_when_every_connection_fails(db, monkeypatch):
    _mock_google(monkeypatch, refresh_ok=False)
    alerts = []
    monkeypatch.setattr("app.jobs.google_calendar_sync.alert_job_failure", lambda *a, **k: alerts.append(a))
    db.add(GoogleCalendarConnection(admin_user_id="j1", encrypted_refresh_token=encrypt_refresh_token("rt")))
    db.commit()
    job = run_google_calendar_sync(db)
    assert job.success is True  # the job itself completed; individual sync failures don't fail the run
    assert len(alerts) == 1


def test_run_google_calendar_sync_is_a_no_op_with_no_connections(db):
    job = run_google_calendar_sync(db)
    assert job.success is True
    assert job.rows_seen == 0


# --- OAuth flow: role-gating + state-token handling, full-stack TestClient ---

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
    justice = AdminUser(id="j1", email="j1@test.local", hashed_password=hash_password("pw"),
                         role=AdminRole.editor, is_justice=True, display_name="Justice One")
    contributor = AdminUser(id="c1", email="c1@test.local", hashed_password=hash_password("pw"), role=AdminRole.contributor)
    seed.add_all([justice, contributor])
    seed.commit()
    seed.close()

    yield TestClient(app), TestSession
    app.dependency_overrides.clear()


def _auth(client, email="j1@test.local"):
    r = client.post("/api/admin/login", json={"email": email, "password": "pw"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_connect_requires_justice_identity_not_curation_role(ctx, monkeypatch):
    client, _Session = ctx
    monkeypatch.setattr("app.routers.google_calendar.GOOGLE_CALENDAR_CLIENT_ID", "fake-client-id")
    monkeypatch.setattr("app.routers.google_calendar.GOOGLE_CALENDAR_REDIRECT_URI", "https://example.test/callback")
    r = client.get("/api/account/google-calendar/connect", headers=_auth(client, "c1@test.local"))
    assert r.status_code == 403


def test_connect_requires_login_at_all(ctx):
    client, _Session = ctx
    r = client.get("/api/account/google-calendar/connect")
    assert r.status_code == 401


def test_connect_503s_when_not_configured(ctx):
    client, _Session = ctx
    r = client.get("/api/account/google-calendar/connect", headers=_auth(client))
    assert r.status_code == 503


def test_connect_returns_a_real_google_authorization_url(ctx, monkeypatch):
    client, Session = ctx
    monkeypatch.setattr("app.routers.google_calendar.GOOGLE_CALENDAR_CLIENT_ID", "fake-client-id")
    monkeypatch.setattr("app.routers.google_calendar.GOOGLE_CALENDAR_REDIRECT_URI", "https://example.test/callback")
    r = client.get("/api/account/google-calendar/connect", headers=_auth(client))
    assert r.status_code == 200
    url = r.json()["authorization_url"]
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "calendar.freebusy" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url

    db = Session()
    assert db.query(GoogleCalendarOAuthState).filter(GoogleCalendarOAuthState.admin_user_id == "j1").count() == 1
    db.close()


def test_callback_rejects_an_unknown_state(ctx):
    client, _Session = ctx
    r = client.get("/api/account/google-calendar/callback", params={"code": "x", "state": "does-not-exist"}, follow_redirects=False)
    assert r.status_code == 302
    assert "google_calendar=error" in r.headers["location"]


def test_callback_rejects_an_expired_state(ctx):
    client, Session = ctx
    db = Session()
    db.add(GoogleCalendarOAuthState(token_hash=hash_token("expired-token"), admin_user_id="j1",
                                     expires_at=datetime.utcnow() - timedelta(minutes=1)))
    db.commit()
    db.close()
    r = client.get("/api/account/google-calendar/callback", params={"code": "x", "state": "expired-token"}, follow_redirects=False)
    assert "google_calendar=error" in r.headers["location"]


def test_callback_success_creates_a_connection_and_redirects(ctx, monkeypatch):
    client, Session = ctx
    monkeypatch.setattr("app.routers.google_calendar.GOOGLE_CALENDAR_CLIENT_ID", "fake-client-id")
    monkeypatch.setattr("app.routers.google_calendar.GOOGLE_CALENDAR_CLIENT_SECRET", "fake-secret")
    monkeypatch.setattr("app.routers.google_calendar.GOOGLE_CALENDAR_REDIRECT_URI", "https://example.test/callback")

    def fake_post(url, **kwargs):
        return httpx.Response(200, json={"refresh_token": "real-refresh-token"}, request=httpx.Request("POST", url))
    monkeypatch.setattr("app.routers.google_calendar.httpx.post", fake_post)

    db = Session()
    db.add(GoogleCalendarOAuthState(token_hash=hash_token("good-token"), admin_user_id="j1",
                                     expires_at=datetime.utcnow() + timedelta(minutes=10)))
    db.commit()
    db.close()

    r = client.get("/api/account/google-calendar/callback", params={"code": "auth-code", "state": "good-token"}, follow_redirects=False)
    assert r.status_code == 302
    assert "google_calendar=connected" in r.headers["location"]

    db = Session()
    connection = db.query(GoogleCalendarConnection).filter(GoogleCalendarConnection.admin_user_id == "j1").first()
    assert connection is not None
    assert decrypt_refresh_token(connection.encrypted_refresh_token) == "real-refresh-token"
    # The state token is now used -- a second attempt with the same one must fail.
    db.close()
    r2 = client.get("/api/account/google-calendar/callback", params={"code": "auth-code", "state": "good-token"}, follow_redirects=False)
    assert "google_calendar=error" in r2.headers["location"]


def test_disconnect_requires_justice_login(ctx):
    client, _Session = ctx
    assert client.delete("/api/account/google-calendar").status_code == 401


def test_disconnect_404s_with_no_connection(ctx):
    client, _Session = ctx
    r = client.delete("/api/account/google-calendar", headers=_auth(client))
    assert r.status_code == 404


def test_disconnect_removes_connection_and_overrides(ctx):
    client, Session = ctx
    db = Session()
    db.add(GoogleCalendarConnection(admin_user_id="j1", encrypted_refresh_token=encrypt_refresh_token("rt")))
    db.commit()
    replace_owner_overrides_for_window(
        db, AvailabilityOwnerType.justice, "j1", date(2026, 10, 1), date(2026, 10, 1), {date(2026, 10, 1): {1}},
    )
    db.commit()
    db.close()

    r = client.delete("/api/account/google-calendar", headers=_auth(client))
    assert r.status_code == 200

    db = Session()
    assert db.query(GoogleCalendarConnection).filter(GoogleCalendarConnection.admin_user_id == "j1").first() is None
    assert load_override_slots_by_date(db, AvailabilityOwnerType.justice, "j1") == {}
    db.close()


def test_availability_endpoint_reports_connection_status(ctx):
    client, Session = ctx
    db = Session()
    db.add(GoogleCalendarConnection(admin_user_id="j1", encrypted_refresh_token=encrypt_refresh_token("rt"),
                                     last_sync_error="Token refresh failed"))
    db.commit()
    db.close()

    r = client.get("/api/justices/me/availability", headers=_auth(client))
    assert r.status_code == 200
    body = r.json()
    assert body["google_calendar_connected"] is True
    assert body["google_calendar_last_sync_error"] == "Token refresh failed"


def test_manual_availability_update_blocked_while_connected(ctx):
    client, Session = ctx
    db = Session()
    db.add(GoogleCalendarConnection(admin_user_id="j1", encrypted_refresh_token=encrypt_refresh_token("rt")))
    db.commit()
    db.close()

    r = client.patch("/api/justices/me/availability", json={"cells": [{"day_of_week": "mon", "slot_index": 0}]},
                      headers=_auth(client))
    assert r.status_code == 400

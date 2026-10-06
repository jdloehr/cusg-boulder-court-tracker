"""
Phase-4 doc, Section 2.3: real TOTP two-factor authentication and
per-account lockout after repeated failed logins.
"""
from datetime import datetime, timedelta

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.db import get_db
from app.main import app
from app.models import AdminRole, AdminUser, Base
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
    seed.add(AdminUser(email="editor@test.local", hashed_password=hash_password("editor-pw-123"),
                        role=AdminRole.editor, display_name="Editor Editorson"))
    seed.commit()
    seed.close()

    yield TestClient(app), TestSession
    app.dependency_overrides.clear()


def _auth(client, email="editor@test.local", password="editor-pw-123", **extra):
    r = client.post("/api/admin/login", json={"email": email, "password": password, **extra})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _enable_2fa(client, headers):
    setup = client.post("/api/account/2fa/setup", headers=headers)
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    code = pyotp.TOTP(secret).now()
    confirm = client.post("/api/account/2fa/confirm", json={"code": code}, headers=headers)
    assert confirm.status_code == 200, confirm.text
    return secret, confirm.json()["backup_codes"]


def _future_totp_code(secret, steps_ahead=1):
    """A TOTP code for the step right after whatever this account's
    last_accepted_step already is (Oct 2026 review item 6: a code for
    the *same* step pyotp.TOTP(secret).now() would just generate again
    is a replay and gets rejected, not a fresh valid code) -- without
    actually sleeping in a test. Exactly 1 step (30s) ahead, not more:
    the server checks a submitted code against +/-1 step around its
    *own* "now" at verification time (a near-instant later), so 1 step
    ahead both clears the previously-accepted step and still lands
    inside that tolerance window -- 2+ steps ahead would be outside it
    and get rejected as simply wrong, not as a replay."""
    return pyotp.TOTP(secret).at(datetime.now() + timedelta(seconds=30 * steps_ahead))


def _login_with_totp(client, secret, email="editor@test.local", password="editor-pw-123"):
    """A fresh login (and fresh headers) using a not-yet-used TOTP step.
    Needed after _enable_2fa: confirming 2FA bumps token_version (Oct
    2026 review item 7), which revokes the pre-2FA session that was used
    to call /2fa/confirm -- correct, deliberate behavior (a token issued
    before 2FA existed on the account shouldn't keep working
    indefinitely once it's turned on), but callers need a fresh,
    2FA-aware token to do anything authenticated afterward."""
    r = client.post("/api/admin/login", json={
        "email": email, "password": password, "totp_code": _future_totp_code(secret),
    })
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# --- 2FA setup/confirm/disable -----------------------------------------------

def test_setup_refuses_with_409_when_2fa_is_already_enabled(ctx):
    """Oct 2026 review item 5: calling setup again used to silently
    replace the active secret with a new, unconfirmed one -- no
    password, no proof of anything -- which would have locked the
    account's *real* second factor out from under its owner (every
    future login's TOTP check would run against a secret no
    authenticator app has ever been enrolled with). Disabling 2FA
    already requires the password; this makes "set up a replacement"
    route through that instead of silently doubling as a bypass."""
    client, Session = ctx
    headers = _auth(client)
    secret, _backup_codes = _enable_2fa(client, headers)
    headers = _login_with_totp(client, secret)

    db = Session()
    secret_before = db.query(AdminUser).filter(AdminUser.email == "editor@test.local").first().totp_secret
    db.close()

    again = client.post("/api/account/2fa/setup", headers=headers)
    assert again.status_code == 409

    db = Session()
    user = db.query(AdminUser).filter(AdminUser.email == "editor@test.local").first()
    assert user.totp_secret == secret_before == secret  # unchanged -- not silently replaced
    assert user.totp_enabled is True
    db.close()


def test_setup_returns_a_working_secret_and_qr_code(ctx):
    client, _Session = ctx
    headers = _auth(client)
    r = client.post("/api/account/2fa/setup", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body["secret"]) >= 16
    assert body["qr_code_data_uri"].startswith("data:image/png;base64,")
    assert body["secret"] in body["provisioning_uri"]


def test_confirm_rejects_a_wrong_code(ctx):
    client, _Session = ctx
    headers = _auth(client)
    client.post("/api/account/2fa/setup", headers=headers)
    r = client.post("/api/account/2fa/confirm", json={"code": "000000"}, headers=headers)
    assert r.status_code == 400


def test_confirm_with_a_real_code_enables_2fa_and_returns_backup_codes(ctx):
    client, _Session = ctx
    headers = _auth(client)
    _secret, backup_codes = _enable_2fa(client, headers)
    assert len(backup_codes) == 8
    assert len(set(backup_codes)) == 8  # all unique


def test_login_after_2fa_enabled_requires_a_code(ctx):
    client, _Session = ctx
    headers = _auth(client)
    _enable_2fa(client, headers)

    no_code = client.post("/api/admin/login", json={"email": "editor@test.local", "password": "editor-pw-123"})
    assert no_code.status_code == 428


def test_login_with_a_valid_totp_code_succeeds(ctx):
    client, _Session = ctx
    headers = _auth(client)
    secret, _backup_codes = _enable_2fa(client, headers)

    # A fresh step, not the one _enable_2fa's own confirm call already
    # consumed (Oct 2026 review item 6: that exact code is now a
    # rejected replay, not a valid one -- see
    # test_a_totp_code_cannot_be_reused_for_a_second_login below).
    r = client.post("/api/admin/login", json={
        "email": "editor@test.local", "password": "editor-pw-123", "totp_code": _future_totp_code(secret),
    })
    assert r.status_code == 200


def test_a_totp_code_cannot_be_reused_for_a_second_login(ctx):
    """Oct 2026 review item 6: the defining behavior of replay
    protection -- the exact same code that just worked is rejected the
    second time, even though it's still within its normal +/-1 step
    validity window and would otherwise still pyotp-verify just fine."""
    client, _Session = ctx
    headers = _auth(client)
    secret, _backup_codes = _enable_2fa(client, headers)
    code = _future_totp_code(secret)

    first = client.post("/api/admin/login", json={
        "email": "editor@test.local", "password": "editor-pw-123", "totp_code": code,
    })
    assert first.status_code == 200

    second = client.post("/api/admin/login", json={
        "email": "editor@test.local", "password": "editor-pw-123", "totp_code": code,
    })
    assert second.status_code == 401


def test_login_with_a_wrong_totp_code_fails(ctx):
    client, _Session = ctx
    headers = _auth(client)
    _enable_2fa(client, headers)

    r = client.post("/api/admin/login", json={
        "email": "editor@test.local", "password": "editor-pw-123", "totp_code": "000000",
    })
    assert r.status_code == 401


def test_login_with_a_backup_code_works_once(ctx):
    client, _Session = ctx
    headers = _auth(client)
    _secret, backup_codes = _enable_2fa(client, headers)
    code = backup_codes[0]

    first = client.post("/api/admin/login", json={
        "email": "editor@test.local", "password": "editor-pw-123", "totp_code": code,
    })
    assert first.status_code == 200

    second = client.post("/api/admin/login", json={
        "email": "editor@test.local", "password": "editor-pw-123", "totp_code": code,
    })
    assert second.status_code == 401


def test_disable_2fa_requires_correct_password(ctx):
    client, _Session = ctx
    headers = _auth(client)
    secret, _backup_codes = _enable_2fa(client, headers)
    # Oct 2026 review item 7: confirming 2FA just revoked the headers
    # above (token_version bumped) -- need a fresh, 2FA-aware login to
    # do anything authenticated from here.
    headers = _login_with_totp(client, secret)

    wrong = client.post("/api/account/2fa/disable", json={"password": "not-the-password"}, headers=headers)
    assert wrong.status_code == 401

    right = client.post("/api/account/2fa/disable", json={"password": "editor-pw-123"}, headers=headers)
    assert right.status_code == 200

    # 2FA no longer required to log in.
    r = client.post("/api/admin/login", json={"email": "editor@test.local", "password": "editor-pw-123"})
    assert r.status_code == 200


# --- Account lockout / backoff (Oct 2026 review item 4) ---------------------
#
# Replaces the original flat 10-failure/15-minute lockout (a real
# denial-of-service lever -- anyone who knows an account's email could
# lock it out for everyone, including its real owner, just by throwing
# 10 wrong passwords at it) and its distinct 423 response (which leaked
# whether an email had an account before a single credential was ever
# checked) with per-account exponential backoff and a response
# indistinguishable from a plain wrong password. See
# app/routers/admin.py's _login_backoff_seconds/_DUMMY_PASSWORD_HASH.

def test_account_locks_after_repeated_failed_attempts(ctx):
    client, Session = ctx
    for i in range(10):
        r = client.post("/api/admin/login", json={"email": "editor@test.local", "password": "wrong"})
        assert r.status_code == 401, f"attempt {i} should still be a plain 401, got {r.status_code}"

    db = Session()
    user = db.query(AdminUser).filter(AdminUser.email == "editor@test.local").first()
    assert user.locked_until is not None
    db.close()


def test_locked_account_rejects_even_the_correct_password_with_a_plain_401(ctx):
    """Not 423 any more -- a backed-off account has to be indistinguishable
    from a wrong password, or the response itself would leak that this
    account exists and has had recent failed attempts."""
    client, Session = ctx
    db = Session()
    from datetime import datetime, timedelta
    user = db.query(AdminUser).filter(AdminUser.email == "editor@test.local").first()
    user.locked_until = datetime.utcnow() + timedelta(minutes=15)
    db.commit()
    db.close()

    r = client.post("/api/admin/login", json={"email": "editor@test.local", "password": "editor-pw-123"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid credentials"


def test_unknown_email_gets_the_identical_response_as_a_wrong_password(ctx):
    """The whole point of _DUMMY_PASSWORD_HASH: an attacker (or a
    curious visitor) can't tell "no such account" apart from "wrong
    password for a real one" from the response alone."""
    client, _Session = ctx
    unknown = client.post("/api/admin/login", json={"email": "nobody@test.local", "password": "whatever"})
    wrong = client.post("/api/admin/login", json={"email": "editor@test.local", "password": "wrong"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json() == {"detail": "Invalid credentials"}


def test_first_two_failures_cost_no_backoff_at_all(ctx):
    """LOGIN_BACKOFF_GRACE_ATTEMPTS=2 -- ordinary typos shouldn't cost
    anything."""
    client, Session = ctx
    for _ in range(2):
        client.post("/api/admin/login", json={"email": "editor@test.local", "password": "wrong"})

    db = Session()
    user = db.query(AdminUser).filter(AdminUser.email == "editor@test.local").first()
    assert user.locked_until is None
    db.close()

    # A correct password right after is accepted immediately -- nothing
    # to wait out yet.
    ok = client.post("/api/admin/login", json={"email": "editor@test.local", "password": "editor-pw-123"})
    assert ok.status_code == 200


def test_login_backoff_seconds_grows_with_each_additional_failure():
    """Pure-function check of the growth curve itself -- a real HTTP
    round trip can't easily exercise several growing delays in sequence
    without either sleeping in the test or re-triggering the "still
    backed off, bounce early" branch (see
    test_a_request_made_while_backed_off_does_not_extend_the_backoff
    below for that distinct behavior)."""
    from app.routers.admin import LOGIN_BACKOFF_GRACE_ATTEMPTS, _login_backoff_seconds

    assert LOGIN_BACKOFF_GRACE_ATTEMPTS == 2
    assert [_login_backoff_seconds(n) for n in range(1, 8)] == [0, 0, 2, 4, 8, 16, 32]


def test_login_backoff_seconds_is_capped_at_five_minutes():
    from app.routers.admin import LOGIN_BACKOFF_MAX_SECONDS, _login_backoff_seconds
    assert LOGIN_BACKOFF_MAX_SECONDS == 300
    assert _login_backoff_seconds(1000) == 300


def test_first_backoff_eligible_failure_sets_the_expected_delay(ctx):
    """End-to-end version of the pure-function check above: the 3rd
    failed attempt (the first past the 2-attempt grace period) really
    does set locked_until the expected ~2 seconds out, through the real
    login endpoint."""
    from app.routers.admin import _login_backoff_seconds

    client, Session = ctx
    for _ in range(2):  # exhaust the free grace attempts, unmeasured
        client.post("/api/admin/login", json={"email": "editor@test.local", "password": "wrong"})

    client.post("/api/admin/login", json={"email": "editor@test.local", "password": "wrong"})

    db = Session()
    user = db.query(AdminUser).filter(AdminUser.email == "editor@test.local").first()
    assert user.failed_login_attempts == 3
    delay = (user.locked_until - datetime.utcnow()).total_seconds()
    assert _login_backoff_seconds(3) - 1 <= delay <= _login_backoff_seconds(3) + 1
    db.close()


def test_a_request_made_while_backed_off_does_not_extend_the_backoff(ctx):
    """Deliberate design choice: once backed off, a request (right
    password or wrong) during that window is bounced immediately
    *before* the password is even checked -- it never reaches
    _register_failure(), so it can't further extend the delay or bump
    the counter. This bounds the total wait to whatever the last real
    attempt set, however many times an attacker (or a flaky retry loop)
    hammers the endpoint in the meantime, rather than letting pure
    request volume keep pushing the window out indefinitely."""
    client, Session = ctx
    for _ in range(3):  # 2 free + 1 backoff-eligible failure
        client.post("/api/admin/login", json={"email": "editor@test.local", "password": "wrong"})

    db = Session()
    user = db.query(AdminUser).filter(AdminUser.email == "editor@test.local").first()
    locked_until_after_third_failure = user.locked_until
    attempts_after_third_failure = user.failed_login_attempts
    db.close()

    # Several more attempts land squarely inside that backoff window.
    for _ in range(5):
        r = client.post("/api/admin/login", json={"email": "editor@test.local", "password": "wrong"})
        assert r.status_code == 401

    db = Session()
    user = db.query(AdminUser).filter(AdminUser.email == "editor@test.local").first()
    assert user.locked_until == locked_until_after_third_failure
    assert user.failed_login_attempts == attempts_after_third_failure
    db.close()


def test_successful_login_resets_the_failed_attempt_counter(ctx):
    client, Session = ctx
    # Kept within the no-backoff grace period -- the point here is "a
    # successful login resets the counter," not backoff mechanics
    # (which, by design, also delay a *correct* password once enough
    # failures have happened -- see test_backoff_grows_... above).
    for _ in range(2):
        client.post("/api/admin/login", json={"email": "editor@test.local", "password": "wrong"})

    ok = client.post("/api/admin/login", json={"email": "editor@test.local", "password": "editor-pw-123"})
    assert ok.status_code == 200

    db = Session()
    user = db.query(AdminUser).filter(AdminUser.email == "editor@test.local").first()
    assert user.failed_login_attempts == 0
    assert user.locked_until is None
    db.close()


def test_a_correct_password_is_rejected_while_still_backed_off(ctx):
    """The defining behavior of exponential backoff, not just a flat
    lockout: once enough failures have happened, even the *correct*
    password has to wait out the delay -- it isn't a free pass."""
    client, Session = ctx
    for _ in range(5):  # past the grace period -- sets a real backoff window
        client.post("/api/admin/login", json={"email": "editor@test.local", "password": "wrong"})

    immediately_after = client.post(
        "/api/admin/login", json={"email": "editor@test.local", "password": "editor-pw-123"}
    )
    assert immediately_after.status_code == 401

    # Simulate having actually waited out the window.
    db = Session()
    user = db.query(AdminUser).filter(AdminUser.email == "editor@test.local").first()
    user.locked_until = None
    db.commit()
    db.close()

    after_waiting = client.post(
        "/api/admin/login", json={"email": "editor@test.local", "password": "editor-pw-123"}
    )
    assert after_waiting.status_code == 200

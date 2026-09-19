"""
Phase-4 doc, Section 2.3: real TOTP two-factor authentication and
per-account lockout after repeated failed logins.
"""
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


# --- 2FA setup/confirm/disable -----------------------------------------------

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

    code = pyotp.TOTP(secret).now()
    r = client.post("/api/admin/login", json={
        "email": "editor@test.local", "password": "editor-pw-123", "totp_code": code,
    })
    assert r.status_code == 200


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
    _enable_2fa(client, headers)

    wrong = client.post("/api/account/2fa/disable", json={"password": "not-the-password"}, headers=headers)
    assert wrong.status_code == 401

    right = client.post("/api/account/2fa/disable", json={"password": "editor-pw-123"}, headers=headers)
    assert right.status_code == 200

    # 2FA no longer required to log in.
    r = client.post("/api/admin/login", json={"email": "editor@test.local", "password": "editor-pw-123"})
    assert r.status_code == 200


# --- Account lockout ----------------------------------------------------------

def test_account_locks_after_repeated_failed_attempts(ctx):
    client, Session = ctx
    for i in range(10):
        r = client.post("/api/admin/login", json={"email": "editor@test.local", "password": "wrong"})
        assert r.status_code == 401, f"attempt {i} should still be a plain 401, got {r.status_code}"

    db = Session()
    user = db.query(AdminUser).filter(AdminUser.email == "editor@test.local").first()
    assert user.locked_until is not None
    db.close()


def test_locked_account_rejects_even_the_correct_password(ctx):
    client, Session = ctx
    db = Session()
    from datetime import datetime, timedelta
    user = db.query(AdminUser).filter(AdminUser.email == "editor@test.local").first()
    user.locked_until = datetime.utcnow() + timedelta(minutes=15)
    db.commit()
    db.close()

    r = client.post("/api/admin/login", json={"email": "editor@test.local", "password": "editor-pw-123"})
    assert r.status_code == 423


def test_successful_login_resets_the_failed_attempt_counter(ctx):
    client, Session = ctx
    for _ in range(5):
        client.post("/api/admin/login", json={"email": "editor@test.local", "password": "wrong"})

    ok = client.post("/api/admin/login", json={"email": "editor@test.local", "password": "editor-pw-123"})
    assert ok.status_code == 200

    db = Session()
    user = db.query(AdminUser).filter(AdminUser.email == "editor@test.local").first()
    assert user.failed_login_attempts == 0
    db.close()

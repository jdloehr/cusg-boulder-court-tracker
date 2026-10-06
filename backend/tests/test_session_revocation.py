"""
Oct 2026 review item 7: AdminUser.token_version, embedded in every JWT
and checked on every authenticated request. Bumping it immediately
invalidates every token issued before the bump -- previously there was
no way to revoke an already-issued session short of rotating JWT_SECRET,
which logs out every account, not just the one that needed it.

The individual revocation triggers (password reset, invite accept, 2FA
enable/disable) are covered incidentally where they're tested already
(test_accounts.py, test_two_factor_and_lockout.py); this file covers the
token_version mechanism itself directly.
"""
import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import create_access_token, hash_password
from app.config import JWT_ALGORITHM, JWT_SECRET
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
    editor = AdminUser(email="editor@test.local", hashed_password=hash_password("editor-pw-123"),
                        role=AdminRole.editor, display_name="Editor Editorson")
    seed.add(editor)
    seed.commit()
    seed.close()

    yield TestClient(app), TestSession
    app.dependency_overrides.clear()


def test_create_access_token_embeds_the_current_token_version(ctx):
    _client, Session = ctx
    db = Session()
    user = db.query(AdminUser).filter(AdminUser.email == "editor@test.local").first()
    assert user.token_version == 0  # column default
    token = create_access_token(user)
    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    assert payload["token_version"] == 0
    db.close()


def test_bumping_token_version_invalidates_a_previously_issued_token(ctx):
    client, Session = ctx
    r = client.post("/api/admin/login", json={"email": "editor@test.local", "password": "editor-pw-123"})
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    # Works before the bump.
    ok = client.get("/api/admin/activity-log", headers=headers)
    assert ok.status_code == 200

    db = Session()
    user = db.query(AdminUser).filter(AdminUser.email == "editor@test.local").first()
    user.token_version += 1
    db.commit()
    db.close()

    revoked = client.get("/api/admin/activity-log", headers=headers)
    assert revoked.status_code == 401

    # A fresh login (fresh token, current token_version) works again.
    r2 = client.post("/api/admin/login", json={"email": "editor@test.local", "password": "editor-pw-123"})
    fresh_headers = {"Authorization": f"Bearer {r2.json()['access_token']}"}
    ok_again = client.get("/api/admin/activity-log", headers=fresh_headers)
    assert ok_again.status_code == 200


def test_a_token_with_no_token_version_claim_still_works_while_the_account_is_at_version_zero(ctx):
    """Backward compatibility for a token issued before this check
    existed (no claim at all, not just version 0) -- rolling this out
    shouldn't force-logout every already-signed-in account; it should
    only start mattering the next time one of them resets a password,
    accepts an invite, or toggles 2FA."""
    client, Session = ctx
    db = Session()
    user = db.query(AdminUser).filter(AdminUser.email == "editor@test.local").first()
    assert user.token_version == 0
    db.close()

    payload = {"sub": user.id, "email": user.email, "role": user.role.value, "is_justice": False}
    import datetime
    payload["exp"] = datetime.datetime.utcnow() + datetime.timedelta(minutes=5)
    legacy_token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

    r = client.get("/api/admin/activity-log", headers={"Authorization": f"Bearer {legacy_token}"})
    assert r.status_code == 200


def test_a_legacy_no_claim_token_stops_working_once_the_account_is_bumped(ctx):
    client, Session = ctx
    db = Session()
    user = db.query(AdminUser).filter(AdminUser.email == "editor@test.local").first()
    user_id, user_email, user_role = user.id, user.email, user.role.value
    user.token_version += 1
    db.commit()
    db.close()

    import datetime
    payload = {
        "sub": user_id, "email": user_email, "role": user_role, "is_justice": False,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(minutes=5),
    }
    legacy_token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

    r = client.get("/api/admin/activity-log", headers={"Authorization": f"Bearer {legacy_token}"})
    assert r.status_code == 401

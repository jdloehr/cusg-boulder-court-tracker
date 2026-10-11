"""
Phase-3 doc: invite-link provisioning (Section 1), sign-in support --
forgot/reset password (Section 2), and public Justice profiles + photo
upload (Section 3). Same TestClient + isolated in-memory-DB pattern as
test_justices.py / test_archive.py.
"""
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import hash_password, hash_token
from app.db import get_db
from app.main import app
from app.models import AdminInvite, AdminRole, AdminUser, Base, JusticeAllowlistEntry, PasswordResetToken
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
    justice = AdminUser(email="joshua@test.local", hashed_password=hash_password("justice-pw-123"),
                         is_justice=True, role=AdminRole.editor, display_name="Joshua Loehr",
                         title="Associate Justice")
    seed.add_all([editor, justice])
    seed.commit()
    seed.close()

    yield TestClient(app), TestSession
    app.dependency_overrides.clear()


def _auth(client, email, password):
    r = client.post("/api/admin/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# --- Section 1: invites ------------------------------------------------------

def test_editor_can_create_invite_and_it_returns_a_usable_link(ctx):
    client, _Session = ctx
    headers = _auth(client, "editor@test.local", "editor-pw-123")
    r = client.post("/api/admin/invites", json={
        "email": "new.justice@test.local", "display_name": "New Justice", "title": "Associate Justice",
    }, headers=headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "new.justice@test.local"
    assert "/accept-invite/" in body["invite_link"]


def test_non_editor_cannot_create_invite(ctx):
    client, Session = ctx
    db = Session()
    db.add(AdminUser(email="contributor@test.local", hashed_password=hash_password("contrib-pw-123"),
                      role=AdminRole.contributor))
    db.commit()
    db.close()
    headers = _auth(client, "contributor@test.local", "contrib-pw-123")
    r = client.post("/api/admin/invites", json={
        "email": "x@test.local", "display_name": "X",
    }, headers=headers)
    assert r.status_code == 403


def test_accepting_an_invite_creates_a_justice_account_with_editor_role(ctx):
    """Phase-3 doc, Section 2's explicit 'merge now' choice: a brand-new
    Justice account provisioned via invite gets role=editor directly, not
    just is_justice=True."""
    client, _Session = ctx
    headers = _auth(client, "editor@test.local", "editor-pw-123")
    link = client.post("/api/admin/invites", json={
        "email": "new.justice@test.local", "display_name": "New Justice", "title": "Associate Justice",
    }, headers=headers).json()["invite_link"]
    token = link.rsplit("/", 1)[-1]

    info = client.get(f"/api/invites/{token}")
    assert info.status_code == 200
    assert info.json() == {
        "email": "new.justice@test.local", "display_name": "New Justice",
        "title": "Associate Justice", "expires_at": info.json()["expires_at"],
    }

    accepted = client.post(f"/api/invites/{token}/accept", json={"password": "a-strong-passw0rd"})
    assert accepted.status_code == 200, accepted.text
    body = accepted.json()
    assert body["is_justice"] is True
    assert body["role"] == "editor"
    assert body["display_name"] == "New Justice"

    # And the new account can log in for real, and reach an Editor-only endpoint.
    new_headers = {"Authorization": f"Bearer {body['access_token']}"}
    admin_check = client.get("/api/admin/review-queue/hearings", headers=new_headers)
    assert admin_check.status_code == 200


def test_invite_is_single_use(ctx):
    client, _Session = ctx
    headers = _auth(client, "editor@test.local", "editor-pw-123")
    link = client.post("/api/admin/invites", json={
        "email": "new.justice@test.local", "display_name": "New Justice",
    }, headers=headers).json()["invite_link"]
    token = link.rsplit("/", 1)[-1]

    first = client.post(f"/api/invites/{token}/accept", json={"password": "a-strong-passw0rd"})
    assert first.status_code == 200
    second = client.post(f"/api/invites/{token}/accept", json={"password": "another-passw0rd"})
    assert second.status_code == 410


def test_expired_invite_is_rejected(ctx):
    client, Session = ctx
    from datetime import datetime, timedelta
    db = Session()
    token = "expired-token-value"
    db.add(AdminInvite(email="late@test.local", display_name="Late Justice",
                        token_hash=hash_token(token), created_by_email="editor@test.local",
                        expires_at=datetime.utcnow() - timedelta(hours=1)))
    db.commit()
    db.close()
    r = client.get(f"/api/invites/{token}")
    assert r.status_code == 410


def test_accept_invite_rejects_a_weak_password(ctx):
    client, _Session = ctx
    headers = _auth(client, "editor@test.local", "editor-pw-123")
    link = client.post("/api/admin/invites", json={
        "email": "new.justice@test.local", "display_name": "New Justice",
    }, headers=headers).json()["invite_link"]
    token = link.rsplit("/", 1)[-1]
    r = client.post(f"/api/invites/{token}/accept", json={"password": "short"})
    assert r.status_code == 422


# --- Self-service invite requests, gated by an Editor-maintained allow-list --

def test_editor_can_manage_the_allowlist(ctx):
    client, _Session = ctx
    headers = _auth(client, "editor@test.local", "editor-pw-123")

    created = client.post("/api/admin/justice-allowlist", json={
        "email": "future.justice@test.local", "display_name": "Future Justice", "title": "Associate Justice",
    }, headers=headers)
    assert created.status_code == 201, created.text
    entry_id = created.json()["id"]

    listed = client.get("/api/admin/justice-allowlist", headers=headers)
    assert listed.status_code == 200
    assert any(e["email"] == "future.justice@test.local" for e in listed.json())

    removed = client.delete(f"/api/admin/justice-allowlist/{entry_id}", headers=headers)
    assert removed.status_code == 200
    assert client.get("/api/admin/justice-allowlist", headers=headers).json() == []


def test_non_editor_cannot_manage_the_allowlist(ctx):
    client, Session = ctx
    db = Session()
    db.add(AdminUser(email="contributor@test.local", hashed_password=hash_password("contrib-pw-123"),
                      role=AdminRole.contributor))
    db.commit()
    db.close()
    headers = _auth(client, "contributor@test.local", "contrib-pw-123")
    r = client.post("/api/admin/justice-allowlist", json={
        "email": "x@test.local", "display_name": "X",
    }, headers=headers)
    assert r.status_code == 403


def test_allowlisted_email_can_self_request_an_invite(ctx, monkeypatch):
    client, _Session = ctx
    sent = []
    monkeypatch.setattr("app.routers.account.send_email", lambda to, subject, body: sent.append((to, subject, body)))

    headers = _auth(client, "editor@test.local", "editor-pw-123")
    client.post("/api/admin/justice-allowlist", json={
        "email": "future.justice@test.local", "display_name": "Future Justice", "title": "Associate Justice",
    }, headers=headers)

    r = client.post("/api/justices/request-invite", json={"email": "future.justice@test.local"})
    assert r.status_code == 200
    assert len(sent) == 1
    assert sent[0][0] == "future.justice@test.local"
    assert "/accept-invite/" in sent[0][2]

    # The link in the email is real and completes the same accept flow.
    token = sent[0][2].rsplit("/accept-invite/", 1)[-1].split()[0]
    accepted = client.post(f"/api/invites/{token}/accept", json={"password": "a-strong-passw0rd"})
    assert accepted.status_code == 200
    assert accepted.json()["display_name"] == "Future Justice"
    assert accepted.json()["role"] == "editor"


def test_unlisted_email_gets_the_same_generic_response_and_no_email(ctx, monkeypatch):
    client, _Session = ctx
    sent = []
    monkeypatch.setattr("app.routers.account.send_email", lambda to, subject, body: sent.append((to, subject, body)))

    listed = client.post("/api/justices/request-invite", json={"email": "nobody-knows-me@test.local"})
    assert listed.status_code == 200
    assert sent == []


def test_request_invite_is_case_insensitive_on_email(ctx, monkeypatch):
    client, Session = ctx
    sent = []
    monkeypatch.setattr("app.routers.account.send_email", lambda to, subject, body: sent.append((to, subject, body)))

    db = Session()
    db.add(JusticeAllowlistEntry(email="Future.Justice@Test.Local", display_name="Future Justice",
                                  added_by_email="editor@test.local"))
    db.commit()
    db.close()

    r = client.post("/api/justices/request-invite", json={"email": "future.justice@test.local"})
    assert r.status_code == 200
    assert len(sent) == 1


def test_request_invite_is_rate_limited(ctx):
    client, _Session = ctx
    for _ in range(5):
        client.post("/api/justices/request-invite", json={"email": "nobody@test.local"})
    blocked = client.post("/api/justices/request-invite", json={"email": "nobody@test.local"})
    assert blocked.status_code == 429


def test_adding_to_allowlist_does_not_by_itself_grant_login(ctx):
    """Being on the allow-list only lets someone *request* an invite --
    it doesn't create an AdminUser or grant any access on its own."""
    client, _Session = ctx
    headers = _auth(client, "editor@test.local", "editor-pw-123")
    client.post("/api/admin/justice-allowlist", json={
        "email": "future.justice@test.local", "display_name": "Future Justice",
    }, headers=headers)
    r = client.post("/api/admin/login", json={"email": "future.justice@test.local", "password": "anything"})
    assert r.status_code == 401


# --- Section 2: forgot / reset password --------------------------------------

def test_forgot_password_always_returns_generic_success(ctx):
    client, _Session = ctx
    real = client.post("/api/auth/forgot-password", json={"email": "joshua@test.local"})
    fake = client.post("/api/auth/forgot-password", json={"email": "nobody@test.local"})
    assert real.status_code == 200
    assert fake.status_code == 200
    assert real.json()["message"] == fake.json()["message"]


def test_reset_password_with_valid_token_changes_password(ctx, monkeypatch):
    client, _Session = ctx
    # send_email is stubbed to logging (app/config.py's EMAIL_BACKEND), so
    # the raw token (never persisted -- only its hash is) is otherwise
    # unreachable from a test; pin what the endpoint generates instead of
    # reading the DB for it, same idea as monkeypatching send_email
    # elsewhere in this test suite.
    monkeypatch.setattr("app.routers.account.generate_secure_token", lambda: "known-reset-token")

    r = client.post("/api/auth/forgot-password", json={"email": "joshua@test.local"})
    assert r.status_code == 200

    reset = client.post("/api/auth/reset-password/known-reset-token",
                         json={"password": "a-new-strong-passw0rd"})
    assert reset.status_code == 200

    old = client.post("/api/admin/login", json={"email": "joshua@test.local", "password": "justice-pw-123"})
    assert old.status_code == 401
    new = client.post("/api/admin/login", json={"email": "joshua@test.local", "password": "a-new-strong-passw0rd"})
    assert new.status_code == 200


def test_reset_password_token_is_single_use(ctx):
    client, Session = ctx
    from app.auth import generate_secure_token
    from datetime import datetime, timedelta
    token = generate_secure_token()
    db = Session()
    justice = db.query(AdminUser).filter(AdminUser.email == "joshua@test.local").first()
    db.add(PasswordResetToken(admin_user_id=justice.id, token_hash=hash_token(token),
                              expires_at=datetime.utcnow() + timedelta(hours=1)))
    db.commit()
    db.close()

    first = client.post(f"/api/auth/reset-password/{token}", json={"password": "a-new-strong-passw0rd"})
    assert first.status_code == 200
    second = client.post(f"/api/auth/reset-password/{token}", json={"password": "yet-another-passw0rd"})
    assert second.status_code == 410


# --- Section 3: profiles + photo ---------------------------------------------

def test_justice_can_view_and_edit_own_profile(ctx):
    client, _Session = ctx
    headers = _auth(client, "joshua@test.local", "justice-pw-123")
    r = client.patch("/api/justices/me/profile", json={
        "bio": "Third-year, interested in appellate practice.",
        "year_or_major": "Political Science, Junior",
        "why_care": "Court-watching made the law feel real.",
        "fun_fact": "Once sat through a full week-long jury trial.",
    }, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["bio"] == "Third-year, interested in appellate practice."

    directory = client.get("/api/justices").json()
    mine = next(j for j in directory if j["display_name"] == "Joshua Loehr")
    assert mine["fun_fact"] == "Once sat through a full week-long jury trial."

    single = client.get(f"/api/justices/{mine['id']}")
    assert single.status_code == 200
    assert single.json()["bio"] == "Third-year, interested in appellate practice."


def test_non_justice_cannot_edit_a_profile(ctx):
    client, Session = ctx
    db = Session()
    db.add(AdminUser(email="contributor@test.local", hashed_password=hash_password("contrib-pw-123"),
                      role=AdminRole.contributor))
    db.commit()
    db.close()
    headers = _auth(client, "contributor@test.local", "contrib-pw-123")
    r = client.patch("/api/justices/me/profile", json={"bio": "hi"}, headers=headers)
    assert r.status_code == 403


def _fake_jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (400, 300), color=(10, 20, 30)).save(buf, format="JPEG")
    return buf.getvalue()


def test_photo_upload_validates_process_and_serves(ctx):
    client, _Session = ctx
    headers = _auth(client, "joshua@test.local", "justice-pw-123")

    r = client.put(
        "/api/justices/me/photo",
        headers=headers,
        files={"file": ("me.jpg", _fake_jpeg_bytes(), "image/jpeg")},
    )
    assert r.status_code == 200, r.text
    photo_url = r.json()["photo_url"]
    assert photo_url

    served = client.get(photo_url)
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/jpeg"
    assert len(served.content) > 0


def test_photo_upload_rejects_non_image_file(ctx):
    client, _Session = ctx
    headers = _auth(client, "joshua@test.local", "justice-pw-123")
    r = client.put(
        "/api/justices/me/photo",
        headers=headers,
        files={"file": ("me.txt", b"not an image at all", "text/plain")},
    )
    assert r.status_code == 400


def test_photo_endpoint_404s_when_no_photo_uploaded(ctx):
    client, Session = ctx
    db = Session()
    justice = db.query(AdminUser).filter(AdminUser.email == "joshua@test.local").first()
    justice_id = justice.id
    db.close()
    r = client.get(f"/api/justices/{justice_id}/photo")
    assert r.status_code == 404


# --- Login rate limiting (Section 5) -----------------------------------------

def test_login_is_rate_limited_per_ip(ctx):
    client, _Session = ctx
    for _ in range(10):
        client.post("/api/admin/login", json={"email": "joshua@test.local", "password": "wrong"})
    blocked = client.post("/api/admin/login", json={"email": "joshua@test.local", "password": "wrong"})
    assert blocked.status_code == 429

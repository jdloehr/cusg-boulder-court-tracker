"""
Phase-3 doc: Justice account provisioning (Section 1), sign-in support --
password reset (Section 2), and public Justice profiles (Section 3).

Provisioning is invite-link, not open self-registration or a shared code
(Section 6.1's explicit choice): an existing Editor/Justice enters a real
person's name+email here (POST /admin/invites), and the resulting
one-time, expiring link is what lets that person set their own password
and become an account -- see AdminInvite's docstring in app/models.py for
why the token itself is never stored in plaintext.

Signing in as a Justice now also grants full curation access (Section 2's
explicit "merge now" choice, reversing this build's earlier "keep
separate" stance) -- implemented here by setting role=AdminRole.editor
directly on every Justice account this module creates, not by changing
what require_editor checks. See AdminUser's docstring in app/models.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from sqlalchemy.orm import Session

from app.auth import (
    create_access_token,
    generate_secure_token,
    hash_password,
    hash_token,
    require_editor,
    require_justice,
)
from app.config import FRONTEND_URL, INVITE_EXPIRE_HOURS, PASSWORD_RESET_EXPIRE_HOURS
from app.db import get_db
from app.jobs.digest import send_email
from app.models import AdminInvite, AdminRole, AdminUser, PasswordResetToken
from app.photo import InvalidPhotoError, process_profile_photo
from app.rate_limit import check_rate_limit, client_ip
from app.schemas import (
    AdminLoginResponse,
    ForgotPasswordIn,
    InviteAcceptIn,
    InviteCreateIn,
    InviteInfoOut,
    InviteOut,
    JusticeOut,
    JusticeProfileIn,
    ResetPasswordIn,
)

router = APIRouter(tags=["accounts"])


def _photo_url(justice: AdminUser) -> str | None:
    return f"/api/justices/{justice.id}/photo" if justice.photo_data else None


def _justice_out(j: AdminUser) -> JusticeOut:
    return JusticeOut(
        id=j.id, display_name=j.display_name or j.email, title=j.title,
        bio=j.bio, year_or_major=j.year_or_major, why_care=j.why_care, fun_fact=j.fun_fact,
        photo_url=_photo_url(j),
    )


# --- Section 1: invite-link provisioning ------------------------------------

@router.post("/api/admin/invites", response_model=InviteOut, status_code=201)
def create_invite(payload: InviteCreateIn, db: Session = Depends(get_db),
                   admin: AdminUser = Depends(require_editor)):
    """Editor-only (or, after Section 2's merge, any Justice -- they're
    the same thing now). Invalidates any previously-issued, still-unused
    invite for this email first, so re-inviting someone (fixing a typo,
    or effectively resetting them before they ever set a password)
    doesn't leave two valid links outstanding."""
    now = datetime.utcnow()
    db.query(AdminInvite).filter(
        AdminInvite.email == payload.email, AdminInvite.used_at.is_(None)
    ).update({"used_at": now})

    token = generate_secure_token()
    expires_at = now + timedelta(hours=INVITE_EXPIRE_HOURS)
    invite = AdminInvite(
        email=payload.email, display_name=payload.display_name, title=payload.title,
        token_hash=hash_token(token), created_by_email=admin.email, expires_at=expires_at,
    )
    db.add(invite)
    db.commit()

    link = f"{FRONTEND_URL}/accept-invite/{token}"
    send_email(
        payload.email,
        "You're invited to the CUSG Boulder Court Tracker",
        f"{admin.display_name or admin.email} has invited you to set up your CUSG Justice "
        f"account as {payload.display_name}.\n\nSet your password here (expires in "
        f"{INVITE_EXPIRE_HOURS} hours, one-time use):\n{link}",
    )
    return InviteOut(email=payload.email, display_name=payload.display_name, expires_at=expires_at,
                      invite_link=link)


def _load_valid_invite(db: Session, token: str) -> AdminInvite:
    invite = db.query(AdminInvite).filter(AdminInvite.token_hash == hash_token(token)).first()
    if not invite:
        raise HTTPException(404, "Invite not found")
    if invite.used_at is not None:
        raise HTTPException(410, "This invite link has already been used")
    if invite.expires_at < datetime.utcnow():
        raise HTTPException(410, "This invite link has expired -- ask for a new one")
    return invite


@router.get("/api/invites/{token}", response_model=InviteInfoOut)
def get_invite(token: str, db: Session = Depends(get_db)):
    """Public -- what the accept-invite page shows before a password is
    set. Only ever exposes what InviteInfoOut lists; never the token
    itself (already in the URL) or any internal fields."""
    invite = _load_valid_invite(db, token)
    return InviteInfoOut(email=invite.email, display_name=invite.display_name,
                          title=invite.title, expires_at=invite.expires_at)


@router.post("/api/invites/{token}/accept", response_model=AdminLoginResponse)
def accept_invite(token: str, payload: InviteAcceptIn, db: Session = Depends(get_db)):
    """Public (the token itself is the credential). Creates the account
    if this email has none yet, or updates it in place if it does (a
    re-invite after a typo, or a deliberate reset) -- either way ends by
    logging the new Justice straight in, so they land on their own
    profile-edit page without a second sign-in step."""
    invite = _load_valid_invite(db, token)

    user = db.query(AdminUser).filter(AdminUser.email == invite.email).first()
    if user is None:
        user = AdminUser(email=invite.email)
        db.add(user)
    user.hashed_password = hash_password(payload.password)
    user.display_name = invite.display_name
    user.title = invite.title
    user.is_justice = True
    # Section 2's explicit "merge now" choice: every Justice account is
    # also a full Editor. See AdminUser's docstring in app/models.py.
    user.role = AdminRole.editor
    user.is_active = True

    invite.used_at = datetime.utcnow()
    db.commit()
    db.refresh(user)

    return AdminLoginResponse(
        access_token=create_access_token(user), id=user.id, role=user.role.value if user.role else None,
        is_justice=user.is_justice, display_name=user.display_name, title=user.title,
    )


# --- Section 2: forgot password ----------------------------------------------

@router.post("/api/auth/forgot-password")
def forgot_password(payload: ForgotPasswordIn, request: Request, db: Session = Depends(get_db)):
    """Always returns the same generic response regardless of whether the
    email matches an account -- otherwise this endpoint would let anyone
    check which email addresses have accounts (a small, semi-public
    roster of 7-8 people, but no reason to leak it anyway). Rate-limited
    per IP so it can't be used to spam an inbox with reset emails."""
    if not check_rate_limit(f"forgot-password:{client_ip(request)}", max_requests=5, window_seconds=600):
        raise HTTPException(429, "Too many requests -- try again in a few minutes.")

    user = db.query(AdminUser).filter(AdminUser.email == payload.email, AdminUser.is_active.is_(True)).first()
    if user:
        token = generate_secure_token()
        expires_at = datetime.utcnow() + timedelta(hours=PASSWORD_RESET_EXPIRE_HOURS)
        db.add(PasswordResetToken(admin_user_id=user.id, token_hash=hash_token(token), expires_at=expires_at))
        db.commit()
        link = f"{FRONTEND_URL}/reset-password/{token}"
        send_email(
            user.email, "Reset your CUSG Boulder Court Tracker password",
            f"Reset your password here (expires in {PASSWORD_RESET_EXPIRE_HOURS} hours, "
            f"one-time use):\n{link}\n\nIf you didn't request this, ignore this email.",
        )
    return {"status": "ok", "message": "If that email has an account, a reset link has been sent."}


@router.post("/api/auth/reset-password/{token}")
def reset_password(token: str, payload: ResetPasswordIn, db: Session = Depends(get_db)):
    reset = db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == hash_token(token)).first()
    if not reset:
        raise HTTPException(404, "Reset link not found")
    if reset.used_at is not None:
        raise HTTPException(410, "This reset link has already been used")
    if reset.expires_at < datetime.utcnow():
        raise HTTPException(410, "This reset link has expired -- request a new one")

    user = db.query(AdminUser).filter(AdminUser.id == reset.admin_user_id).first()
    if not user or not user.is_active:
        raise HTTPException(404, "Account not found")

    user.hashed_password = hash_password(payload.password)
    reset.used_at = datetime.utcnow()
    db.commit()
    return {"status": "reset"}


# --- Section 3: public Justice profiles --------------------------------------

@router.patch("/api/justices/me/profile", response_model=JusticeOut)
def update_my_profile(payload: JusticeProfileIn, db: Session = Depends(get_db),
                       justice: AdminUser = Depends(require_justice)):
    """A Justice edits only their own profile -- identity comes from the
    login (require_justice), never a ?justice_id= the caller could swap
    out for someone else's."""
    if payload.bio is not None:
        justice.bio = payload.bio
    if payload.year_or_major is not None:
        justice.year_or_major = payload.year_or_major
    if payload.why_care is not None:
        justice.why_care = payload.why_care
    if payload.fun_fact is not None:
        justice.fun_fact = payload.fun_fact
    db.commit()
    db.refresh(justice)
    return _justice_out(justice)


@router.put("/api/justices/me/photo", response_model=JusticeOut)
async def upload_my_photo(db: Session = Depends(get_db), file: UploadFile = File(...),
                           justice: AdminUser = Depends(require_justice)):
    raw = await file.read()
    try:
        jpeg_bytes, content_type = process_profile_photo(raw, file.content_type or "")
    except InvalidPhotoError as exc:
        raise HTTPException(400, str(exc)) from exc

    justice.photo_data = jpeg_bytes
    justice.photo_content_type = content_type
    db.commit()
    db.refresh(justice)
    return _justice_out(justice)


@router.get("/api/justices/{justice_id}/photo")
def get_justice_photo(justice_id: str, db: Session = Depends(get_db)):
    """Public. Serves the re-encoded JPEG bytes directly (see
    app/photo.py) -- no caching header beyond the default, since a
    Justice can replace their photo at any time and this is low-traffic
    enough that staleness isn't worth trading for cache correctness."""
    justice = db.query(AdminUser).filter(AdminUser.id == justice_id).first()
    if not justice or not justice.photo_data:
        raise HTTPException(404, "No photo")
    return Response(content=justice.photo_data, media_type=justice.photo_content_type or "image/jpeg")

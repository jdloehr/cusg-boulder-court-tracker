"""
Phase-3 doc: Justice account provisioning (Section 1), sign-in support --
password reset (Section 2), and public Justice profiles (Section 3).

Provisioning is invite-link, not open self-registration or a shared code
(Section 6.1's explicit choice): a real person's name+email has to reach
AdminInvite before they can set a password and become an account -- see
AdminInvite's docstring in app/models.py for why the token itself is
never stored in plaintext. Two ways to get there, both live:
- An existing Editor/Justice invites someone directly
  (POST /admin/invites) -- the original design.
- A known Justice self-serves their own link
  (POST /justices/request-invite), added on request once "I have to
  already have an account to invite anyone, including myself" turned out
  to be a real bootstrapping problem. Still gated the same way: only an
  email an Editor has already added to JusticeAllowlistEntry can trigger
  a real send -- see that model's docstring in app/models.py.

Signing in as a Justice now also grants full curation access (Section 2's
explicit "merge now" choice, reversing this build's earlier "keep
separate" stance) -- implemented here by setting role=AdminRole.editor
directly on every Justice account this module creates, not by changing
what require_editor checks. See AdminUser's docstring in app/models.py.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import (
    create_access_token,
    generate_secure_token,
    get_current_admin,
    hash_password,
    hash_token,
    require_editor,
    require_justice,
    verify_password,
)
from app.availability import NUM_SLOTS, WEEKDAY_ABBRS, hearing_matches_slots, parse_hearing_time
from app.availability_slots import load_free_slots_by_day, load_owner_cells, replace_owner_slots
from app.config import FRONTEND_URL, INVITE_EXPIRE_HOURS, PASSWORD_RESET_EXPIRE_HOURS
from app.db import get_db
from app.jobs.digest import send_email
from app.models import (
    AdminInvite,
    AdminRole,
    AdminUser,
    AvailabilityOwnerType,
    Hearing,
    JusticeAllowlistEntry,
    PasswordResetToken,
)
from app.photo import InvalidPhotoError, process_profile_photo
from app.rate_limit import check_rate_limit, client_ip
from app.schemas import (
    AdminLoginResponse,
    AllowlistEntryIn,
    AllowlistEntryOut,
    AvailabilitySummaryEntry,
    AvailabilitySummaryRequest,
    ForgotPasswordIn,
    InviteAcceptIn,
    InviteCreateIn,
    InviteInfoOut,
    InviteOut,
    JusticeAvailabilityIn,
    JusticeAvailabilityOut,
    JusticeOut,
    JusticeProfileIn,
    RequestInviteIn,
    ResetPasswordIn,
    TeamAvailabilityCell,
    TeamAvailabilityOut,
    TotpConfirmIn,
    TotpConfirmOut,
    TotpDisableIn,
    TotpSetupOut,
)
from app.totp import (
    consume_backup_code,
    generate_backup_codes,
    generate_totp_secret,
    provisioning_uri,
    qr_code_data_uri,
    verify_totp_code,
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

def _issue_invite(db: Session, *, email: str, display_name: str, title: str | None,
                   invited_by: str, email_body: str) -> InviteOut:
    """Shared by the Editor-direct flow (create_invite) and the
    self-service flow (request_invite): invalidate any previously-issued,
    still-unused invite for this email first (so re-inviting someone --
    fixing a typo, or effectively resetting them before they ever set a
    password -- doesn't leave two valid links outstanding), then create
    and send a fresh one."""
    now = datetime.utcnow()
    db.query(AdminInvite).filter(
        AdminInvite.email == email, AdminInvite.used_at.is_(None)
    ).update({"used_at": now})

    token = generate_secure_token()
    expires_at = now + timedelta(hours=INVITE_EXPIRE_HOURS)
    invite = AdminInvite(
        email=email, display_name=display_name, title=title,
        token_hash=hash_token(token), created_by_email=invited_by, expires_at=expires_at,
    )
    db.add(invite)
    db.commit()

    link = f"{FRONTEND_URL}/accept-invite/{token}"
    send_email(email, "Set up your CUSG Boulder Court Tracker account", email_body.format(link=link))
    return InviteOut(email=email, display_name=display_name, expires_at=expires_at, invite_link=link)


@router.post("/api/admin/invites", response_model=InviteOut, status_code=201)
def create_invite(payload: InviteCreateIn, db: Session = Depends(get_db),
                   admin: AdminUser = Depends(require_editor)):
    """Editor-only (or, after Section 2's merge, any Justice -- they're
    the same thing now): invite someone directly, without them needing to
    know the self-service page (request_invite, below) exists."""
    return _issue_invite(
        db, email=payload.email, display_name=payload.display_name, title=payload.title,
        invited_by=admin.email,
        email_body=(
            f"{admin.display_name or admin.email} has invited you to set up your CUSG Justice "
            f"account as {payload.display_name}.\n\nSet your password here (expires in "
            f"{INVITE_EXPIRE_HOURS} hours, one-time use):\n{{link}}"
        ),
    )


# --- Self-service invite requests, gated by an Editor-maintained allow-list --

@router.post("/api/admin/justice-allowlist", response_model=AllowlistEntryOut, status_code=201)
def add_to_allowlist(payload: AllowlistEntryIn, db: Session = Depends(get_db),
                      admin: AdminUser = Depends(require_editor)):
    """The actual gate behind self-service provisioning: adding someone
    here is what lets them later request their own invite link. Adding an
    email that's already listed just updates the name/title on file
    rather than erroring, so fixing a typo doesn't need a delete-then-
    re-add."""
    existing = db.query(JusticeAllowlistEntry).filter(
        func.lower(JusticeAllowlistEntry.email) == payload.email.strip().lower()
    ).first()
    if existing:
        existing.display_name = payload.display_name
        existing.title = payload.title
        entry = existing
    else:
        entry = JusticeAllowlistEntry(
            email=payload.email.strip(), display_name=payload.display_name,
            title=payload.title, added_by_email=admin.email,
        )
        db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.get("/api/admin/justice-allowlist", response_model=list[AllowlistEntryOut])
def list_allowlist(db: Session = Depends(get_db), admin: AdminUser = Depends(require_editor)):
    return db.query(JusticeAllowlistEntry).order_by(JusticeAllowlistEntry.created_at).all()


@router.delete("/api/admin/justice-allowlist/{entry_id}")
def remove_from_allowlist(entry_id: str, db: Session = Depends(get_db),
                           admin: AdminUser = Depends(require_editor)):
    entry = db.query(JusticeAllowlistEntry).filter(JusticeAllowlistEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(404, "Not found")
    db.delete(entry)
    db.commit()
    return {"status": "removed"}


@router.post("/api/justices/request-invite")
def request_invite(payload: RequestInviteIn, request: Request, db: Session = Depends(get_db)):
    """Public, self-service: a known Justice enters their own email and
    gets their own signup link sent, without needing an existing Editor/
    Justice to trigger it for them. Always returns the same generic
    response regardless of whether the email is allow-listed -- same
    anti-enumeration reasoning as forgot_password below -- and is rate-
    limited per IP so it can't be used to spam an inbox."""
    if not check_rate_limit(f"request-invite:{client_ip(request)}", max_requests=5, window_seconds=600):
        raise HTTPException(429, "Too many requests -- try again in a few minutes.")

    entry = db.query(JusticeAllowlistEntry).filter(
        func.lower(JusticeAllowlistEntry.email) == payload.email.strip().lower()
    ).first()
    if entry:
        _issue_invite(
            db, email=entry.email, display_name=entry.display_name, title=entry.title,
            invited_by=entry.added_by_email,
            email_body=(
                "You're on the CUSG Justice list -- set your password here (expires in "
                f"{INVITE_EXPIRE_HOURS} hours, one-time use):\n{{link}}"
            ),
        )
    return {"status": "ok", "message": "If that email is on the CUSG Justice list, a signup link has been sent."}


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
def accept_invite(token: str, payload: InviteAcceptIn, request: Request, db: Session = Depends(get_db)):
    """Public (the token itself is the credential). Creates the account
    if this email has none yet, or updates it in place if it does (a
    re-invite after a typo, or a deliberate reset) -- either way ends by
    logging the new Justice straight in, so they land on their own
    profile-edit page without a second sign-in step.

    Rate-limited per IP (Phase-4 doc, Section 2.2) -- belt-and-suspenders
    given the token itself is already a high-entropy secret, same
    reasoning as reset_password below."""
    if not check_rate_limit(f"invite-accept:{client_ip(request)}", max_requests=10, window_seconds=600):
        raise HTTPException(429, "Too many attempts from this address -- try again in a few minutes.")
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
def reset_password(token: str, payload: ResetPasswordIn, request: Request, db: Session = Depends(get_db)):
    """Rate-limited per IP (Phase-4 doc, Section 2.2) -- belt-and-
    suspenders given the token itself is already a high-entropy secret
    (guessing it isn't computationally feasible either way)."""
    if not check_rate_limit(f"reset-password:{client_ip(request)}", max_requests=10, window_seconds=600):
        raise HTTPException(429, "Too many attempts from this address -- try again in a few minutes.")
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


# --- Phase-6.2/6.3 docs: Justice-only recurring availability ----------------
# Deliberately separate from /me/profile's JusticeOut-based shape --
# availability must never be reachable through the same schema the public
# roster/profile endpoints return (Section 4: "completely invisible to
# non-Justice/public users, both in the UI and in any API response").
# Phase-6.3 doc replaced the range-block JSON columns with AvailabilitySlot
# rows (a real weekly grid, painted cell-by-cell) -- see
# app/availability_slots.py for the shared load/replace helpers.

@router.get("/api/justices/me/availability", response_model=JusticeAvailabilityOut)
def get_my_availability(justice: AdminUser = Depends(require_justice), db: Session = Depends(get_db)):
    return JusticeAvailabilityOut(cells=load_owner_cells(db, AvailabilityOwnerType.justice, justice.id))


@router.patch("/api/justices/me/availability", response_model=JusticeAvailabilityOut)
def update_my_availability(payload: JusticeAvailabilityIn, db: Session = Depends(get_db),
                            justice: AdminUser = Depends(require_justice)):
    """Full-replace semantics: send the complete current cell list, not
    an incremental add/remove."""
    replace_owner_slots(db, AvailabilityOwnerType.justice, justice.id, payload.cells)
    db.commit()
    return JusticeAvailabilityOut(cells=payload.cells)


@router.post("/api/hearings/availability-summary", response_model=dict[str, AvailabilitySummaryEntry])
def hearings_availability_summary(payload: AvailabilitySummaryRequest, db: Session = Depends(get_db),
                                   justice: AdminUser = Depends(require_justice)):
    """Justice-only (require_justice -- identity-gated, since this is
    "is a real Justice," not curation authority). Takes the exact
    hearing_ids the frontend already has from its own GET /api/hearings
    call rather than re-deriving a date range here, so the meter can
    never disagree with whatever filters (type/category/court/news-only)
    the caller already applied on that other endpoint."""
    hearings = db.query(Hearing).filter(Hearing.id.in_(payload.hearing_ids)).all()
    justices = db.query(AdminUser).filter(
        AdminUser.is_justice.is_(True), AdminUser.is_active.is_(True)
    ).all()
    justice_slots = [
        (j, load_free_slots_by_day(db, AvailabilityOwnerType.justice, j.id))
        for j in justices
    ]

    result: dict[str, AvailabilitySummaryEntry] = {}
    for hearing in hearings:
        free_names = [
            j.display_name or j.email
            for j, free_slots_by_day in justice_slots
            if hearing_matches_slots(hearing.date, hearing.time, hearing.duration, free_slots_by_day)
        ]
        result[hearing.id] = AvailabilitySummaryEntry(
            free_count=len(free_names),
            total=len(justices),
            free_justice_names=free_names,
            time_known=parse_hearing_time(hearing.time) is not None,
        )
    return result


@router.get("/api/justices/team/availability", response_model=TeamAvailabilityOut)
def team_availability(db: Session = Depends(get_db), justice: AdminUser = Depends(require_justice)):
    """Phase-6.3 doc, Section 4: the full weekly heatmap, every one of the
    7*NUM_SLOTS cells precomputed in one pass -- Justice-gated (identity,
    not curation role) and never reachable by a non-Justice, same as the
    per-hearing meter above.

    Deliberately two path segments, not `/api/justices/team-availability`
    -- a single segment there would structurally collide with (and lose
    to, since justices.router is included first in app/main.py)
    `GET /api/justices/{justice_id}` in routers/justices.py, which would
    otherwise treat "team-availability" as a justice id and 404. Same
    reasoning as /api/justices/me/availability already being two
    segments."""
    justices = db.query(AdminUser).filter(
        AdminUser.is_justice.is_(True), AdminUser.is_active.is_(True)
    ).all()
    justice_slots = [
        (j, load_free_slots_by_day(db, AvailabilityOwnerType.justice, j.id))
        for j in justices
    ]

    cells = []
    for day in WEEKDAY_ABBRS:
        for slot_index in range(NUM_SLOTS):
            free_names = [
                j.display_name or j.email
                for j, free_slots_by_day in justice_slots
                if slot_index in free_slots_by_day.get(day, set())
            ]
            cells.append(TeamAvailabilityCell(
                day_of_week=day, slot_index=slot_index,
                free_count=len(free_names), total=len(justices), free_justice_names=free_names,
            ))
    return TeamAvailabilityOut(total_justices=len(justices), cells=cells)


# --- Phase-4 doc, Section 2.3: two-factor authentication --------------------
# Available to any authenticated account (Justice or curation-only Editor/
# Contributor) via get_current_admin -- not require_justice/require_editor,
# since account security isn't specific to either role.

@router.post("/api/account/2fa/setup", response_model=TotpSetupOut)
def setup_2fa(db: Session = Depends(get_db), admin: AdminUser = Depends(get_current_admin)):
    """Generates a new secret and returns it as both a QR code and plain
    text for manual entry -- doesn't take effect until confirm_2fa proves
    the account holder actually has it working. Calling this again before
    confirming just replaces the pending secret (e.g. the QR code expired
    off-screen, or scanning failed) -- harmless since nothing is enabled
    yet either way."""
    secret = generate_totp_secret()
    admin.totp_secret = secret
    db.commit()
    uri = provisioning_uri(secret, admin.email)
    return TotpSetupOut(secret=secret, provisioning_uri=uri, qr_code_data_uri=qr_code_data_uri(uri))


@router.post("/api/account/2fa/confirm", response_model=TotpConfirmOut)
def confirm_2fa(payload: TotpConfirmIn, db: Session = Depends(get_db),
                 admin: AdminUser = Depends(get_current_admin)):
    if not admin.totp_secret:
        raise HTTPException(400, "Start setup first (POST /api/account/2fa/setup)")
    if not verify_totp_code(admin.totp_secret, payload.code):
        raise HTTPException(400, "That code didn't match -- check your authenticator app and try again")

    plaintext_codes, hashed_codes = generate_backup_codes()
    admin.totp_enabled = True
    admin.totp_backup_code_hashes = json.dumps(hashed_codes)
    db.commit()
    return TotpConfirmOut(backup_codes=plaintext_codes)


@router.post("/api/account/2fa/disable")
def disable_2fa(payload: TotpDisableIn, db: Session = Depends(get_db),
                 admin: AdminUser = Depends(get_current_admin)):
    if not verify_password(payload.password, admin.hashed_password):
        raise HTTPException(401, "Incorrect password")
    admin.totp_secret = None
    admin.totp_enabled = False
    admin.totp_backup_code_hashes = None
    db.commit()
    return {"status": "disabled"}

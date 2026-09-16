"""
Admin/curation-team auth (Section 5.4 / 7: "Role-gated login exists only for
the admin/curation team ... none required to browse"). Simple email+password
+ JWT bearer token; no student-facing accounts anywhere in this app.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import JWT_ALGORITHM, JWT_EXPIRE_MINUTES, JWT_SECRET
from app.db import get_db
from app.models import AdminRole, AdminUser

bearer_scheme = HTTPBearer()
optional_bearer_scheme = HTTPBearer(auto_error=False)

# Calls bcrypt directly rather than through passlib's CryptContext.
# Real bug hit during a routine dependency-hygiene check (docs/
# SECURITY_REVIEW.md): passlib 1.7.4 (its last release, in 2020, and
# effectively unmaintained since) probes `bcrypt.__about__.__version__` to
# detect the installed bcrypt version; that submodule was removed in
# bcrypt 4.1+, which makes passlib's version probe fail and its bcrypt
# backend fall back to a code path that mishandles the 72-byte input
# limit, raising ValueError on every hash/verify call. Pinning bcrypt back
# below 4.1 forever to keep an unmaintained wrapper working isn't a real
# fix for a security-sensitive package; calling the actively-maintained
# `bcrypt` library directly (it's a two-function job -- hash and check)
# removes the broken layer instead.
_BCRYPT_MAX_BYTES = 72  # bcrypt's own input limit; longer inputs are truncated, same as before via passlib


def hash_password(password: str) -> str:
    truncated = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(truncated, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    truncated = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    try:
        return bcrypt.checkpw(truncated, hashed.encode("utf-8"))
    except ValueError:
        return False  # malformed/foreign hash format -- treat as a failed verification, not a crash


def create_access_token(user: AdminUser) -> str:
    payload = {
        "sub": user.id,
        "email": user.email,
        # A justice-only account has no curation role -- see AdminUser's
        # docstring in app/models.py for why role and is_justice are
        # separate, independent fields.
        "role": user.role.value if user.role else None,
        "is_justice": user.is_justice,
        "exp": datetime.utcnow() + timedelta(minutes=JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def get_current_admin(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> AdminUser:
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

    user = db.query(AdminUser).filter(AdminUser.id == payload.get("sub")).first()
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not found or disabled")
    return user


def get_optional_admin(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_bearer_scheme),
    db: Session = Depends(get_db),
) -> Optional[AdminUser]:
    """For endpoints public to anyone but that behave differently for a
    logged-in Justice (Phase-2 doc, Section 5: the Archive's "Submit a
    Summary" vs. "Mark Attendance" both hit the same POST endpoint,
    distinguished by whether this returns someone). Never raises -- a
    missing or invalid token just means "not logged in", not an error."""
    if credentials is None:
        return None
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None
    user = db.query(AdminUser).filter(AdminUser.id == payload.get("sub")).first()
    return user if (user and user.is_active) else None


def require_editor(user: AdminUser = Depends(get_current_admin)) -> AdminUser:
    if user.role != AdminRole.editor:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Editor role required")
    return user


def require_justice(user: AdminUser = Depends(get_current_admin)) -> AdminUser:
    if not user.is_justice:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Justice account required")
    return user


# --- Phase-3 doc, Sections 1 & 2: invite links + password reset --------

MIN_PASSWORD_LENGTH = 10


def validate_password_strength(password: str) -> str:
    """Shared by invite-accept and password-reset (app/schemas.py calls
    this from a Pydantic validator). Deliberately simple -- length plus
    "not just letters" -- rather than an arbitrary complexity checklist
    (a required-uppercase-and-symbol rule mostly just pushes people
    towards "Password1!"); the real strength lever for a small, invite-
    only roster is length. Raises ValueError (Pydantic wraps that into a
    422) rather than HTTPException, since it runs inside a validator."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    if password.isalpha() or password.isdigit():
        raise ValueError("Password must mix letters and numbers (or other characters), not just one kind")
    return password


def generate_secure_token() -> str:
    """A one-time invite/password-reset link's token -- high-entropy and
    URL-safe. Returned to the caller (embedded in the emailed link) and
    only ever stored as its hash (see hash_token) -- see AdminInvite's
    docstring for why."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256 is fine here (unlike passwords): these tokens are already
    high-entropy random strings, not human-chosen secrets an attacker
    could dictionary-guess, so there's no need for bcrypt's deliberate
    slowness -- just a one-way transform so a database read alone can't
    hand out a working invite/reset link."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

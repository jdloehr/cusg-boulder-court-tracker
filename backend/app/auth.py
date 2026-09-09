"""
Admin/curation-team auth (Section 5.4 / 7: "Role-gated login exists only for
the admin/curation team ... none required to browse"). Simple email+password
+ JWT bearer token; no student-facing accounts anywhere in this app.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import JWT_ALGORITHM, JWT_EXPIRE_MINUTES, JWT_SECRET
from app.db import get_db
from app.models import AdminRole, AdminUser

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


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


def require_editor(user: AdminUser = Depends(get_current_admin)) -> AdminUser:
    if user.role != AdminRole.editor:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Editor role required")
    return user


def require_justice(user: AdminUser = Depends(get_current_admin)) -> AdminUser:
    if not user.is_justice:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Justice account required")
    return user

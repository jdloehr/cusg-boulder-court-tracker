"""
One-time Justice login-email updates, driven entirely by the
JUSTICE_EMAIL_UPDATES environment variable (app/config.py) rather than a
hardcoded mapping in this file -- real people's real email addresses
have no business living in this public repository's source or git
history, the same reasoning FRONTEND_URL/SENDGRID_API_KEY are env vars
instead of constants.

Runs automatically at every backend startup (same reasoning as
app/migrations.py: this Render plan has no Shell/one-off-job access, so
a change that isn't automatic at boot has nowhere to run at all) but is
naturally idempotent without any special-casing: once an account's email
has been changed, the old address in the mapping no longer matches
anything, so re-running this on every future boot -- including forever,
if the env var is just left set -- is a silent no-op.

Example JUSTICE_EMAIL_UPDATES value:
    {"dillon.rankin@cusg-justices.local": "dillon.rankin@colorado.edu"}

After an email is updated, that Justice's existing password still works
(the account itself -- id, role, profile, attendance/recommendation
history -- is untouched, only the login address changes); if they don't
know it, the existing "Forgot your password?" flow now works for their
new address, same as it would for anyone else.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session, sessionmaker

from app.config import JUSTICE_EMAIL_UPDATES
from app.models import AdminUser

logger = logging.getLogger(__name__)


def apply_email_updates(db: Session, mapping: dict[str, str]) -> list[str]:
    """Pure and testable: takes an already-open session and an explicit
    mapping, returns the list of "old -> new" changes actually made.
    Skips (and logs) a pair where the old address has no matching
    account, or the new address is already taken by a different one --
    never raises, since a startup hook failing shouldn't block the app
    from booting."""
    applied = []
    for old_email, new_email in mapping.items():
        if old_email == new_email:
            continue
        user = db.query(AdminUser).filter(AdminUser.email == old_email).first()
        if not user:
            continue  # already applied in a previous run, or the old address was never real
        conflict = db.query(AdminUser).filter(AdminUser.email == new_email).first()
        if conflict:
            logger.error(
                "JUSTICE_EMAIL_UPDATES: can't change %s -> %s, %s is already in use by another account",
                old_email, new_email, new_email,
            )
            continue
        user.email = new_email
        applied.append(f"{old_email} -> {new_email}")
    db.commit()
    return applied


def run_from_env(engine) -> None:
    if not JUSTICE_EMAIL_UPDATES:
        return
    try:
        mapping = json.loads(JUSTICE_EMAIL_UPDATES)
    except json.JSONDecodeError:
        logger.error("JUSTICE_EMAIL_UPDATES is set but isn't valid JSON -- skipping")
        return
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        applied = apply_email_updates(db, mapping)
        for change in applied:
            logger.info("JUSTICE_EMAIL_UPDATES applied: %s", change)
    finally:
        db.close()

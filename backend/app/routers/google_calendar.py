"""
Calendar-sync doc: the OAuth connect/callback/disconnect flow for
Justice Google Calendar sync. app/jobs/google_calendar_sync.py is the
recurring sync itself; this module is just how a connection gets
created or removed.

Scope is deliberately `calendar.freebusy` only -- checked directly
against Google's current API docs before relying on it: this scope can
query freeBusy but cannot list a user's calendars (that needs the much
broader calendar.readonly, which also grants full event-content read
access). That's why there's no "pick a calendar" endpoint here -- every
connection starts on "primary" (a real, documented Google alias, not a
guess), with an optional calendar-id override for a Justice who knows a
different calendar's own ID. This keeps the doc's privacy promise
literally true -- enforced by the scope Google grants, not just a
policy statement -- at the cost of the picker UI the doc also asked for;
confirmed as the right tradeoff with the user directly, given how much
the doc itself emphasizes the enforcement point.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import generate_secure_token, hash_token, require_justice
from app.config import (
    FRONTEND_URL,
    GOOGLE_CALENDAR_CLIENT_ID,
    GOOGLE_CALENDAR_CLIENT_SECRET,
    GOOGLE_CALENDAR_REDIRECT_URI,
)
from app.db import get_db
from app.models import (
    AdminUser,
    AvailabilityOwnerType,
    GoogleCalendarConnection,
    GoogleCalendarOAuthState,
)
from app.availability_slots import delete_all_owner_overrides, replace_owner_slots
from app.schemas import GoogleCalendarCalendarIdIn, GoogleCalendarConnectOut
from app.token_encryption import encrypt_refresh_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/account/google-calendar", tags=["google-calendar"])

OAUTH_SCOPE = "https://www.googleapis.com/auth/calendar.freebusy"
STATE_EXPIRE_MINUTES = 10  # a Justice completes this round trip within one browser session, not over days


@router.get("/connect", response_model=GoogleCalendarConnectOut)
def start_connect(db: Session = Depends(get_db), justice: AdminUser = Depends(require_justice)):
    if not GOOGLE_CALENDAR_CLIENT_ID or not GOOGLE_CALENDAR_REDIRECT_URI:
        raise HTTPException(503, "Google Calendar sync isn't configured on this server yet.")

    raw_token = generate_secure_token()
    db.add(GoogleCalendarOAuthState(
        token_hash=hash_token(raw_token),
        admin_user_id=justice.id,
        expires_at=datetime.utcnow() + timedelta(minutes=STATE_EXPIRE_MINUTES),
    ))
    db.commit()

    params = {
        "client_id": GOOGLE_CALENDAR_CLIENT_ID,
        "redirect_uri": GOOGLE_CALENDAR_REDIRECT_URI,
        "response_type": "code",
        "scope": OAUTH_SCOPE,
        "access_type": "offline",
        # Guarantees Google issues a refresh token even if this Justice
        # already granted this app access once before (Google otherwise
        # only issues one on the *first* consent for a given app+account).
        "prompt": "consent",
        "state": raw_token,
    }
    return GoogleCalendarConnectOut(authorization_url=f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}")


@router.get("/callback")
def oauth_callback(code: str = Query(...), state: str = Query(...), db: Session = Depends(get_db)):
    """Public -- Google redirects the bare browser here directly, with
    no way to carry a Bearer token. `state` (single-use, hashed at rest,
    10-minute expiry -- same pattern as AdminInvite/PasswordResetToken)
    is what resolves this back to the Justice who started the flow,
    standing in for the auth header a normal API call would have."""
    state_row = db.query(GoogleCalendarOAuthState).filter(GoogleCalendarOAuthState.token_hash == hash_token(state)).first()
    if not state_row or state_row.used_at is not None or state_row.expires_at < datetime.utcnow():
        return RedirectResponse(f"{FRONTEND_URL}/justices/me/edit?google_calendar=error", status_code=302)
    state_row.used_at = datetime.utcnow()

    try:
        resp = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": GOOGLE_CALENDAR_CLIENT_ID,
                "client_secret": GOOGLE_CALENDAR_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": GOOGLE_CALENDAR_REDIRECT_URI,
            },
            timeout=15,
        )
        resp.raise_for_status()
        token_data = resp.json()
        refresh_token = token_data["refresh_token"]
    except (httpx.HTTPError, KeyError) as exc:
        logger.warning("google_calendar oauth_callback: token exchange failed: %s", exc)
        db.commit()  # still mark the state token used even on failure
        return RedirectResponse(f"{FRONTEND_URL}/justices/me/edit?google_calendar=error", status_code=302)

    existing = db.query(GoogleCalendarConnection).filter(GoogleCalendarConnection.admin_user_id == state_row.admin_user_id).first()
    encrypted = encrypt_refresh_token(refresh_token)
    if existing:
        existing.encrypted_refresh_token = encrypted
        existing.last_sync_error = None
    else:
        db.add(GoogleCalendarConnection(admin_user_id=state_row.admin_user_id, encrypted_refresh_token=encrypted))
    db.commit()

    return RedirectResponse(f"{FRONTEND_URL}/justices/me/edit?google_calendar=connected", status_code=302)


@router.post("/calendar-id")
def set_calendar_id(payload: GoogleCalendarCalendarIdIn, db: Session = Depends(get_db),
                     justice: AdminUser = Depends(require_justice)):
    """The doc's "pick which calendar" ask, scoped down to a manual ID
    entry rather than a picker -- see this module's docstring for why."""
    connection = db.query(GoogleCalendarConnection).filter(GoogleCalendarConnection.admin_user_id == justice.id).first()
    if not connection:
        raise HTTPException(404, "No Google Calendar connection -- connect one first.")
    connection.calendar_id = payload.calendar_id.strip() or "primary"
    db.commit()
    return {"status": "updated", "calendar_id": connection.calendar_id}


@router.delete("")
def disconnect(db: Session = Depends(get_db), justice: AdminUser = Depends(require_justice)):
    """Doc: "disconnecting should immediately stop new syncing" (deleting
    the connection row means the next sync run simply never sees it) and
    the Justice's own choice afterward, manual entry or blank -- clearing
    both the override rows *and* the sync-derived recurring baseline is
    the honest "clean fallback": leaving a stale, no-longer-refreshing
    synced pattern in place (on either the per-hearing meter or the
    legacy weekly heatmap) would be worse than a blank grid they can now
    paint by hand, since it would look current when it's actually
    frozen at whatever it was the moment they disconnected."""
    connection = db.query(GoogleCalendarConnection).filter(GoogleCalendarConnection.admin_user_id == justice.id).first()
    if not connection:
        raise HTTPException(404, "No Google Calendar connection to disconnect.")
    db.delete(connection)
    delete_all_owner_overrides(db, AvailabilityOwnerType.justice, justice.id)
    replace_owner_slots(db, AvailabilityOwnerType.justice, justice.id, [])
    db.commit()
    return {"status": "disconnected"}

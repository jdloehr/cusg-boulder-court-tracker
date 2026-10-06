"""
Phase-4 doc, Section 2.3: "upgrade two-factor authentication from
'consider' to a firm recommendation" -- built as real, working TOTP
(RFC 6238, the same standard Google Authenticator/Authy/1Password etc.
implement), not just documented as a good idea. `pyotp` handles the
actual TOTP math; `qrcode` (already depends on Pillow, already a
dependency for profile photos -- see app/photo.py) renders the
provisioning URI as a scannable QR code so setup doesn't require typing
a 32-character secret by hand.

Backup codes exist because losing your phone shouldn't mean losing your
account -- a small, invite-gated roster of 7-8 people is exactly the
group where "no recovery path" turns into a real support burden. Stored
the same way invite/reset tokens are (hashed, single-use): see
app/auth.py::hash_token's docstring for why sha256 (not bcrypt) is the
right tool for an already-high-entropy random string.
"""
from __future__ import annotations

import base64
import io
import secrets
from datetime import datetime
from typing import Optional

import pyotp
import qrcode

from app.auth import hash_token

ISSUER = "CUSG Boulder Court Tracker"
BACKUP_CODE_COUNT = 8


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=ISSUER)


def qr_code_data_uri(uri: str) -> str:
    """A data: URI (base64 PNG) the frontend can drop straight into an
    <img src>, no separate image-hosting endpoint needed for something
    that's only ever shown once, during setup."""
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def verify_totp_code(secret: str, code: str, last_accepted_step: Optional[int] = None) -> tuple[bool, Optional[int]]:
    """Returns (accepted, step) -- `step` is the time step to persist as
    this account's new last_accepted_step on success (AdminUser.
    last_totp_step), or None when the code is rejected.

    Oct 2026 review item 6 (TOTP replay): the previous version just
    returned a bool from pyotp's own .verify(valid_window=1), which
    accepts *any* code within the +/-1 step tolerance every time it's
    checked -- a real TOTP code, once typed (or intercepted, or
    shoulder-surfed), stays valid and reusable for its whole ~90-second
    window, and would still verify a second time 30 seconds later since
    nothing was ever marked "already used." Rejecting anything at or
    before the most recently *accepted* step closes that, at the cost
    of also rejecting an honest same-step double-submit (a flaky
    network retry, say) -- an acceptable trade for a one-time code, and
    the user can just wait for the next one. Same +/-1 step tolerance
    as before for clock drift, just evaluated by hand (pyotp.TOTP.at(),
    not .verify()) so the matching step number is known rather than
    thrown away."""
    if not secret or not code:
        return False, None
    totp = pyotp.TOTP(secret)
    stripped = code.strip()
    current_step = totp.timecode(datetime.now())
    for offset in (-1, 0, 1):
        step = current_step + offset
        if totp.at(step * totp.interval) != stripped:
            continue
        if last_accepted_step is not None and step <= last_accepted_step:
            return False, None  # replay of an already-consumed step
        return True, step
    return False, None


def generate_backup_codes() -> tuple[list[str], list[str]]:
    """Returns (plaintext_codes, hashed_codes) -- plaintext is shown to
    the user exactly once (at 2FA setup) and never stored; hashed is
    what actually gets persisted."""
    plaintext = [secrets.token_hex(4) for _ in range(BACKUP_CODE_COUNT)]
    hashed = [hash_token(code) for code in plaintext]
    return plaintext, hashed


def consume_backup_code(hashed_codes: list[str], submitted_code: str) -> list[str] | None:
    """Returns the remaining hashed-codes list with the matching one
    removed if `submitted_code` matches one of them, else None (no
    match -- caller should treat this as a failed attempt)."""
    submitted_hash = hash_token(submitted_code.strip())
    if submitted_hash not in hashed_codes:
        return None
    return [h for h in hashed_codes if h != submitted_hash]

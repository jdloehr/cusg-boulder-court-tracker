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


def verify_totp_code(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    # valid_window=1 tolerates the code from one 30-second step before/
    # after "now" -- accounts for ordinary clock drift between the
    # server and someone's phone without meaningfully widening the
    # guessable window.
    return pyotp.TOTP(secret).verify(code.strip(), valid_window=1)


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

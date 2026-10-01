"""
Calendar-sync doc: reversible encryption for a Google OAuth refresh
token -- the one secret in this schema that must be *decrypted and
reused* later (to get a fresh access token for the next sync), not just
verified. Every other token in this codebase (AdminInvite,
PasswordResetToken, the OAuth CSRF state below) is one-way hashed via
app.auth.hash_token, which is the right tool when you only ever need to
check "does this match" -- it's the wrong tool here, since there's no
way to turn a hash back into the original token to send to Google.

This codebase has no other reversible encryption anywhere (TOTP secrets
are stored plaintext today -- a separate, pre-existing gap this module
doesn't attempt to fix, since that's unrelated to this feature). Backed
by GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY (app/config.py), a real Fernet
key -- not a passphrase, generated once via Fernet.generate_key() --
following the exact same "a secret env var, dev-only placeholder
locally, a real one required in production" pattern as JWT_SECRET.
Losing or rotating that key in production makes every stored refresh
token permanently undecryptable; affected Justices would just need to
reconnect, the same operational posture as rotating JWT_SECRET logging
every admin session out at once.
"""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.config import GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY


class TokenDecryptionError(ValueError):
    """Raised when a stored token can't be decrypted with the current
    key -- a rotated/misconfigured key, or corrupted data. Callers
    should treat this the same as a revoked token: surface it as a
    sync failure, never crash the whole job."""


def encrypt_refresh_token(raw: str) -> str:
    fernet = Fernet(GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY)
    return fernet.encrypt(raw.encode("utf-8")).decode("utf-8")


def decrypt_refresh_token(encrypted: str) -> str:
    fernet = Fernet(GOOGLE_CALENDAR_TOKEN_ENCRYPTION_KEY)
    try:
        return fernet.decrypt(encrypted.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise TokenDecryptionError("Stored refresh token could not be decrypted") from exc

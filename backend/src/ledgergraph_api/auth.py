"""Password hashing and tokens.

Every primitive that would be dangerous to get wrong comes from a
library: Argon2id from `argon2-cffi`, JWT signing and verification from
`PyJWT`. What is written here is the glue between them and the
repository - which is the part that has to know about *this* system's
rules.

**Why not fastapi-users**, given the tech-stack doc chose it: it needs a
SQLAlchemy or Beanie persistence adapter, and there is no database yet,
so it would need a custom adapter that is throwaway work. More
importantly it ships no refresh-token rotation, and rotation with reuse
detection is the property the architecture doc actually cares about
(risk R5). It remains the right answer for register/verify/reset once
Postgres lands, and the endpoint shapes here match what it produces so
that swap stays cheap.

**Token design**, and the reasoning behind each half:

* the **access token** is a short-lived signed JWT. It is self-contained,
  so a request costs no lookup - and it cannot be revoked, which is why
  it lives 15 minutes rather than a day.
* the **refresh token** is opaque and random, stored only as a hash, and
  **rotated on every use**. Presenting a token that has already been
  consumed revokes the entire family: that is the difference between a
  stolen token being usable indefinitely and being usable once before
  the theft announces itself.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from .config import get_settings

#: Argon2id at the library's defaults, which track current guidance.
#: Chosen over bcrypt for the memory-hardness and because bcrypt silently
#: truncates at 72 bytes - a long passphrase would be weaker than it looks.
_hasher = PasswordHasher()

ALGORITHM = "HS256"
REFRESH_BYTES = 32


class AuthError(Exception):
    """Authentication or authorisation failure, with a stable code."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(detail)


# --------------------------------------------------------------------------
# Passwords
# --------------------------------------------------------------------------

def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time verification. Never raises on a wrong password."""
    try:
        _hasher.verify(hashed, plain)
        return True
    except (VerifyMismatchError, InvalidHashError, Exception):
        return False


def needs_rehash(hashed: str) -> bool:
    """True when the stored hash used weaker parameters than current policy."""
    try:
        return _hasher.check_needs_rehash(hashed)
    except Exception:  # noqa: BLE001 - a malformed hash is replaced anyway
        return True


MIN_PASSWORD_LENGTH = 10


def validate_password(plain: str, *, email: str = "") -> None:
    """Reject the passwords that actually get compromised.

    Length first, because it dominates everything else. The email check
    exists because reusing the local part of an address is common enough
    to be worth naming, and it is invisible to a pure length rule.
    """
    if len(plain) < MIN_PASSWORD_LENGTH:
        raise AuthError(
            "WEAK_PASSWORD",
            f"password must be at least {MIN_PASSWORD_LENGTH} characters",
        )
    local = email.split("@")[0].lower()
    if local and len(local) >= 4 and local in plain.lower():
        raise AuthError("WEAK_PASSWORD", "password must not contain your email name")


# --------------------------------------------------------------------------
# Access tokens
# --------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class AccessClaims:
    user_id: str
    email: str
    role: str
    expires_at: datetime


def mint_access_token(*, user_id: str, email: str, role: str) -> tuple[str, int]:
    """Sign a short-lived access token. Returns (token, seconds_until_expiry)."""
    settings = get_settings()
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=settings.access_token_minutes)

    payload = {
        "sub": user_id,
        "email": email,
        # The role is embedded so a request costs no lookup. The trade is
        # that a role change does not take effect until the current access
        # token expires, which is why that window is 15 minutes.
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "typ": "access",
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)
    return token, settings.access_token_minutes * 60


def read_access_token(token: str) -> AccessClaims:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[ALGORITHM],   # a list, so `alg: none` cannot be honoured
            options={"require": ["exp", "sub", "typ"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("TOKEN_EXPIRED", "access token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("TOKEN_INVALID", "access token is not valid") from exc

    if payload.get("typ") != "access":
        # Without this a refresh token could be presented as an access
        # token, which would defeat the short access lifetime entirely.
        raise AuthError("TOKEN_INVALID", "wrong token type")

    return AccessClaims(
        user_id=payload["sub"],
        email=payload.get("email", ""),
        role=payload.get("role", "analyst"),
        expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
    )


# --------------------------------------------------------------------------
# Refresh tokens
# --------------------------------------------------------------------------

def new_refresh_token() -> tuple[str, str, str]:
    """Return (plaintext, digest, family_id).

    The plaintext goes to the client in an httpOnly cookie and is never
    stored. Only the digest is kept, so a database dump does not yield
    usable sessions.

    A plain SHA-256 is correct here, unlike for passwords: the token is
    32 bytes of CSPRNG output, so there is no guessable input for a slow
    KDF to protect against, and the lookup happens on every refresh.
    """
    plaintext = secrets.token_urlsafe(REFRESH_BYTES)
    return plaintext, digest_refresh_token(plaintext), uuid.uuid4().hex


def digest_refresh_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def refresh_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(days=get_settings().refresh_token_days)


def refresh_cookie_params() -> dict:
    """Cookie attributes for the refresh token.

    `SameSite=None` requires `Secure`, and browsers silently drop a
    cross-site cookie without it - which is why this is derived from the
    environment rather than hardcoded. Locally both ends are on
    `localhost`, so `Lax` works and the cross-site case never shows up in
    development; deployed, the frontend and API are on different hosts
    and it does.
    """
    settings = get_settings()
    cross_site = not settings.is_local
    return {
        "key": "lg_refresh",
        "httponly": True,          # not readable by script, so XSS cannot lift it
        "secure": cross_site,
        "samesite": "none" if cross_site else "lax",
        "path": "/v1/auth",        # sent only to the endpoints that need it
        "max_age": settings.refresh_token_days * 24 * 3600,
    }

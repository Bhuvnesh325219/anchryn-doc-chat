"""Password hashing and access tokens.

Argon2 rather than bcrypt: it is the current recommendation, and bcrypt silently
truncates anything past 72 bytes, which quietly weakens long passwords instead
of failing.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.config import get_settings

logger = logging.getLogger(__name__)

_hasher = PasswordHasher()

ALGORITHM = "HS256"


class InvalidTokenError(Exception):
    """The token was missing, malformed, expired or not signed by us."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time-ish verification that never raises on a bad password."""
    try:
        _hasher.verify(password_hash, password)
        return True
    except VerifyMismatchError:
        return False
    except InvalidHashError:
        # A corrupt or legacy hash. Treated as a failed login rather than a
        # server error — it must not become a way to distinguish accounts.
        logger.warning("Stored password hash could not be parsed")
        return False


def create_access_token(user_id: uuid.UUID) -> str:
    settings = get_settings()
    now = datetime.now(UTC)

    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expiry_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID:
    """Return the user id a token belongs to, or raise InvalidTokenError.

    Every failure mode collapses into one exception with one message: telling a
    caller whether a token was expired versus forged is information they do not
    need and an attacker does.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise InvalidTokenError("Not signed in, or the session has expired.") from exc

"""Security utilities: password hashing, JWT issue/verify, token claims model."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import settings
from app.core.errors import Unauthorized

_ALGORITHM = "HS256"


def hash_password(plain: str) -> str:
    # bcrypt has a 72-byte input limit; enforced at the API schema as well.
    pw = plain.encode("utf-8")[:72]
    return bcrypt.hashpw(pw, bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return False


def _create_token(sub: str, role: str, token_type: str, expires_delta: timedelta) -> tuple[str, str]:
    jti = uuid.uuid4().hex
    now = datetime.now(UTC)
    claims = {
        "sub": sub,
        "role": role,
        "typ": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "jti": jti,
    }
    return jwt.encode(claims, settings.secret_key, algorithm=_ALGORITHM), jti


def create_access_token(sub: str, role: str) -> tuple[str, str]:
    return _create_token(sub, role, "access", timedelta(minutes=settings.access_token_expire_min))


def create_refresh_token(sub: str, role: str) -> tuple[str, str]:
    return _create_token(sub, role, "refresh", timedelta(days=settings.refresh_token_expire_days))


def decode_token(token: str, expected_type: str = "access") -> dict[str, Any]:
    try:
        claims = jwt.decode(token, settings.secret_key, algorithms=[_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise Unauthorized("Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise Unauthorized("Invalid token") from exc
    if claims.get("typ") != expected_type:
        raise Unauthorized(f"Expected {expected_type} token")
    return claims

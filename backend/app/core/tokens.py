"""JWT access/refresh token creation and verification.

Access tokens carry the resolved permission codes (``perms``) so request-time
authorization needs no database round-trip. They are short-lived; permission
changes self-heal on the next refresh. Refresh tokens carry only an identity
and a ``jti`` so they can be rotated and revoked server-side.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt

from app.core.config import settings

TokenType = Literal["access", "refresh"]


class TokenError(Exception):
    """Raised when a token is invalid, expired, or of an unexpected type."""


def _now() -> datetime:
    return datetime.now(tz=UTC)


def create_access_token(
    subject: uuid.UUID,
    tenant_id: uuid.UUID,
    permissions: list[str],
) -> str:
    now = _now()
    payload: dict[str, Any] = {
        "sub": str(subject),
        "tid": str(tenant_id),
        "type": "access",
        "perms": permissions,
        "iat": int(now.timestamp()),
        "exp": int(
            (now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)).timestamp()
        ),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(
    subject: uuid.UUID,
    tenant_id: uuid.UUID,
    jti: uuid.UUID,
) -> str:
    now = _now()
    payload: dict[str, Any] = {
        "sub": str(subject),
        "tid": str(tenant_id),
        "type": "refresh",
        "iat": int(now.timestamp()),
        "exp": int(
            (now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)).timestamp()
        ),
        "jti": str(jti),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    if payload.get("type") != expected_type:
        raise TokenError("Unexpected token type.")
    return payload

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from app.core.tokens import TokenError, decode_token


@dataclass(frozen=True)
class Principal:
    """The authenticated caller, derived from a validated access token."""

    user_id: uuid.UUID
    tenant_id: uuid.UUID
    permissions: frozenset[str]

    def has(self, code: str) -> bool:
        return code in self.permissions


def principal_from_token(token: str) -> Principal:
    """Decode an access token into a Principal. Raises TokenError if invalid."""
    payload = decode_token(token, "access")
    try:
        user_id = uuid.UUID(str(payload["sub"]))
        tenant_id = uuid.UUID(str(payload["tid"]))
    except (KeyError, ValueError) as exc:
        raise TokenError("Malformed token claims.") from exc
    raw = payload.get("perms")
    perms = frozenset(str(p) for p in raw) if isinstance(raw, list) else frozenset()
    return Principal(user_id=user_id, tenant_id=tenant_id, permissions=perms)


def get_principal(request: Request) -> Principal:
    """FastAPI dependency: the Principal placed on the request by AuthMiddleware."""
    principal = getattr(request.state, "principal", None)
    if not isinstance(principal, Principal):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Não autenticado.",
        )
    return principal


async def get_current_tenant_and_user(
    request: Request,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Backward-compatible dependency: (tenant_id, user_id) from the JWT principal."""
    principal = get_principal(request)
    return principal.tenant_id, principal.user_id


def require_permission(code: str) -> Callable[[Request], Principal]:
    """Dependency factory enforcing that the caller holds permission ``code``."""

    def checker(request: Request) -> Principal:
        principal = get_principal(request)
        if not principal.has(code):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permissão necessária: {code}",
            )
        return principal

    return checker

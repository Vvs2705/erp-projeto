"""Authentication and authorization service.

Implements password login with brute-force lockout, refresh-token rotation with
reuse detection, logout (revocation) and role assignment with Segregation-of-
Duties enforcement. All tenant-scoped reads run after binding the tenant for
Row-Level Security.
"""

import hashlib
import hmac
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import set_session_tenant
from app.core.passwords import hash_password, needs_rehash, verify_password
from app.core.permissions import find_sod_violations
from app.core.tokens import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.models.auth import Permission, RefreshToken, Role, RolePermission, UserRole
from app.models.tenant import Tenant, User, UserTenant


class AuthError(Exception):
    """Base authentication/authorization error."""


class InvalidCredentials(AuthError):
    pass


class AccountLocked(AuthError):
    pass


class TenantNotFound(AuthError):
    pass


class NotAMember(AuthError):
    pass


class SoDViolation(AuthError):
    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def resolve_permissions(
    db: AsyncSession, user_id: uuid.UUID, tenant_id: uuid.UUID
) -> list[str]:
    """Return the sorted union of permission codes granted to the user in the tenant."""
    stmt = (
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(
            UserRole.user_id == user_id,
            UserRole.tenant_id == tenant_id,
            Role.tenant_id == tenant_id,
        )
    )
    result = await db.execute(stmt)
    return sorted({row[0] for row in result.all()})


async def _issue_token_pair(
    db: AsyncSession,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    permissions: list[str],
) -> TokenPair:
    access = create_access_token(user_id, tenant_id, permissions)
    jti = uuid.uuid4()
    refresh = create_refresh_token(user_id, tenant_id, jti)
    db.add(
        RefreshToken(
            user_id=user_id,
            tenant_id=tenant_id,
            jti=jti,
            token_hash=_hash_token(refresh),
            expires_at=_utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            revoked=False,
        )
    )
    await db.flush()
    return TokenPair(access_token=access, refresh_token=refresh)


async def login(
    db: AsyncSession, email: str, password: str, tenant_slug: str
) -> TokenPair:
    tenant = (
        await db.execute(select(Tenant).where(Tenant.slug == tenant_slug))
    ).scalar_one_or_none()
    if tenant is None or tenant.status != "active":
        raise TenantNotFound(f"Workspace '{tenant_slug}' não encontrado ou inativo.")

    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if user is None or user.password_hash is None:
        raise InvalidCredentials("E-mail ou senha inválidos.")

    if user.locked_until is not None and user.locked_until > _utcnow():
        raise AccountLocked("Conta temporariamente bloqueada por tentativas inválidas.")

    if not verify_password(password, user.password_hash):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= settings.MAX_FAILED_LOGINS:
            user.locked_until = _utcnow() + timedelta(minutes=settings.LOCKOUT_MINUTES)
            user.failed_login_attempts = 0
        await db.commit()
        raise InvalidCredentials("E-mail ou senha inválidos.")

    await set_session_tenant(db, tenant.id)
    membership = (
        await db.execute(
            select(UserTenant).where(
                UserTenant.user_id == user.id,
                UserTenant.tenant_id == tenant.id,
                UserTenant.status == "active",
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise NotAMember("Usuário não pertence a este workspace.")

    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = _utcnow()
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    permissions = await resolve_permissions(db, user.id, tenant.id)
    pair = await _issue_token_pair(db, user.id, tenant.id, permissions)
    await db.commit()
    return pair


async def refresh(db: AsyncSession, refresh_token: str) -> TokenPair:
    try:
        payload = decode_token(refresh_token, "refresh")
        user_id = uuid.UUID(str(payload["sub"]))
        tenant_id = uuid.UUID(str(payload["tid"]))
        jti = uuid.UUID(str(payload["jti"]))
    except (TokenError, KeyError, ValueError) as exc:
        raise InvalidCredentials("Refresh token inválido.") from exc

    await set_session_tenant(db, tenant_id)
    record = (
        await db.execute(select(RefreshToken).where(RefreshToken.jti == jti))
    ).scalar_one_or_none()

    valid = (
        record is not None
        and not record.revoked
        and record.expires_at > _utcnow()
        and hmac.compare_digest(record.token_hash, _hash_token(refresh_token))
    )
    if not valid:
        # Possible token theft/reuse: defensively revoke all of the user's tokens.
        await db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.tenant_id == tenant_id,
            )
            .values(revoked=True)
        )
        await db.commit()
        raise InvalidCredentials("Refresh token inválido ou revogado.")

    assert record is not None  # noqa: S101 - narrowed by `valid` above
    record.revoked = True
    permissions = await resolve_permissions(db, user_id, tenant_id)
    pair = await _issue_token_pair(db, user_id, tenant_id, permissions)
    await db.commit()
    return pair


async def logout(db: AsyncSession, refresh_token: str) -> None:
    try:
        payload = decode_token(refresh_token, "refresh")
        jti = uuid.UUID(str(payload["jti"]))
        tenant_id = uuid.UUID(str(payload["tid"]))
    except (TokenError, KeyError, ValueError):
        return
    await set_session_tenant(db, tenant_id)
    await db.execute(
        update(RefreshToken).where(RefreshToken.jti == jti).values(revoked=True)
    )
    await db.commit()


async def assign_roles(
    db: AsyncSession,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    role_ids: list[uuid.UUID],
) -> None:
    """Replace a user's roles within a tenant, enforcing Segregation of Duties."""
    stmt = (
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id.in_(role_ids))
    )
    granted = {row[0] for row in (await db.execute(stmt)).all()}
    violations = find_sod_violations(granted)
    if violations:
        raise SoDViolation(violations)

    await db.execute(
        delete(UserRole).where(
            UserRole.user_id == user_id, UserRole.tenant_id == tenant_id
        )
    )
    for rid in role_ids:
        db.add(UserRole(user_id=user_id, tenant_id=tenant_id, role_id=rid))
    await db.commit()

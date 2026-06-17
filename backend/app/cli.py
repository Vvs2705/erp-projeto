"""Operational bootstrap CLI.

Examples:
    python -m app.cli seed-permissions
    python -m app.cli create-owner --tenant-name "Acme" --slug acme \
        --user-name "Ana" --email ana@acme.com   # password via ERP_BOOTSTRAP_PASSWORD

Seeds the permission catalog (reference data) and creates the first tenant and
owner user. The Owner role receives every permission and is exempt from
Segregation of Duties — SoD applies to delegated operational roles, not the
account root.
"""

import argparse
import asyncio
import os
import sys
import uuid

from sqlalchemy import select

from app.core.database import async_session_maker, set_session_tenant
from app.core.passwords import hash_password
from app.core.permissions import PERMISSIONS
from app.models.auth import Permission, Role, RolePermission, UserRole
from app.models.tenant import Tenant, User, UserTenant


async def seed_permissions() -> int:
    """Upsert the permission catalog. Returns the number of new rows."""
    async with async_session_maker() as db:
        existing = {row[0] for row in (await db.execute(select(Permission.code))).all()}
        created = 0
        for p in PERMISSIONS:
            if p.code not in existing:
                db.add(
                    Permission(
                        code=p.code, category=p.category, description=p.description
                    )
                )
                created += 1
        await db.commit()
        return created


async def _ensure_permission_map(db: object) -> dict[str, uuid.UUID]:
    from sqlalchemy.ext.asyncio import AsyncSession

    assert isinstance(db, AsyncSession)  # noqa: S101
    perms: dict[str, uuid.UUID] = {}
    rows = (await db.execute(select(Permission.code, Permission.id))).all()
    for row in rows:
        perms[str(row[0])] = row[1]
    for p in PERMISSIONS:
        if p.code not in perms:
            perm = Permission(
                code=p.code, category=p.category, description=p.description
            )
            db.add(perm)
            await db.flush()
            perms[p.code] = perm.id
    return perms


async def create_owner(
    tenant_name: str, slug: str, user_name: str, email: str, password: str
) -> uuid.UUID:
    """Create (idempotently) the first tenant and its Owner user."""
    email = email.lower()
    async with async_session_maker() as db:
        perms = await _ensure_permission_map(db)

        tenant = (
            await db.execute(select(Tenant).where(Tenant.slug == slug))
        ).scalar_one_or_none()
        if tenant is None:
            tenant = Tenant(name=tenant_name, slug=slug, status="active")
            db.add(tenant)
            await db.flush()

        await set_session_tenant(db, tenant.id)

        user = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if user is None:
            user = User(
                name=user_name,
                email=email,
                status="active",
                password_hash=hash_password(password),
            )
            db.add(user)
            await db.flush()
        else:
            user.password_hash = hash_password(password)

        membership = (
            await db.execute(
                select(UserTenant).where(
                    UserTenant.user_id == user.id,
                    UserTenant.tenant_id == tenant.id,
                )
            )
        ).scalar_one_or_none()
        if membership is None:
            db.add(
                UserTenant(
                    user_id=user.id,
                    tenant_id=tenant.id,
                    role="owner",
                    status="active",
                )
            )

        owner_role = (
            await db.execute(
                select(Role).where(Role.tenant_id == tenant.id, Role.name == "Owner")
            )
        ).scalar_one_or_none()
        if owner_role is None:
            owner_role = Role(
                tenant_id=tenant.id,
                name="Owner",
                description="Acesso total (root). Isento de SoD.",
                is_system=True,
            )
            db.add(owner_role)
            await db.flush()
            for pid in perms.values():
                db.add(RolePermission(role_id=owner_role.id, permission_id=pid))

        has_role = (
            await db.execute(
                select(UserRole).where(
                    UserRole.user_id == user.id,
                    UserRole.tenant_id == tenant.id,
                    UserRole.role_id == owner_role.id,
                )
            )
        ).scalar_one_or_none()
        if has_role is None:
            db.add(
                UserRole(
                    user_id=user.id, tenant_id=tenant.id, role_id=owner_role.id
                )
            )

        await db.commit()
        return tenant.id


def _main() -> int:
    parser = argparse.ArgumentParser(description="ERP-V bootstrap CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed-permissions", help="Upsert the permission catalog")
    owner = sub.add_parser("create-owner", help="Create the first tenant + owner")
    owner.add_argument("--tenant-name", required=True)
    owner.add_argument("--slug", required=True)
    owner.add_argument("--user-name", required=True)
    owner.add_argument("--email", required=True)
    owner.add_argument(
        "--password",
        default=os.environ.get("ERP_BOOTSTRAP_PASSWORD"),
        help="Owner password (or set ERP_BOOTSTRAP_PASSWORD).",
    )
    args = parser.parse_args()

    if args.command == "seed-permissions":
        created = asyncio.run(seed_permissions())
        sys.stdout.write(f"Permissions seeded (new: {created}).\n")
        return 0

    if args.command == "create-owner":
        password = args.password
        if not password:
            sys.stderr.write(
                "Senha obrigatória via --password ou ERP_BOOTSTRAP_PASSWORD.\n"
            )
            return 2
        tenant_id = asyncio.run(
            create_owner(
                args.tenant_name, args.slug, args.user_name, args.email, password
            )
        )
        sys.stdout.write(f"Owner criado. tenant_id={tenant_id}\n")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(_main())

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
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_maker, set_session_tenant
from app.core.passwords import hash_password
from app.core.permissions import PERMISSIONS
from app.models.auth import Permission, Role, RolePermission, UserRole
from app.models.finance import Account, FiscalPeriod, Invoice, Journal
from app.models.tenant import LegalEntity, Organization, Tenant, User, UserTenant
from app.services.finance_service import FinanceService


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
                UserRole(user_id=user.id, tenant_id=tenant.id, role_id=owner_role.id)
            )

        await db.commit()
        return tenant.id


_DEMO_INVOICES = (
    # number, customer, cnpj(14), amount, issue, due, paid_on (or None)
    (
        "NF-001",
        "Alpha Tech LTDA",
        "ALPHATECH00001",
        "15420.00",
        date(2026, 1, 15),
        date(2026, 2, 14),
        date(2026, 1, 20),
    ),
    (
        "NF-002",
        "Industrias Premium SA",
        "PREMIUMSA00001",
        "89100.50",
        date(2026, 2, 10),
        date(2026, 3, 12),
        date(2026, 2, 25),
    ),
    (
        "NF-003",
        "Vortex Servicos de TI",
        "VORTEXTI000001",
        "4290.00",
        date(2026, 3, 5),
        date(2026, 4, 4),
        date(2026, 3, 12),
    ),
    (
        "NF-004",
        "Mercado Confianca LTDA",
        "CONFIANCA00001",
        "23750.00",
        date(2026, 4, 18),
        date(2026, 5, 18),
        None,
    ),
    (
        "NF-005",
        "Beta Logistica SA",
        "BETALOG0000001",
        "33200.00",
        date(2026, 5, 9),
        date(2026, 6, 8),
        date(2026, 5, 15),
    ),
    (
        "NF-006",
        "Gamma Varejo LTDA",
        "GAMMAVAREJO001",
        "51860.00",
        date(2026, 6, 3),
        date(2026, 7, 3),
        None,
    ),
)

_DEMO_BILLS = (
    # number, provider, cnpj(14), amount, issue, due, paid_on (or None)
    (
        "AP-001",
        "Fornecedor Aco LTDA",
        "ACOFORN0000001",
        "32000.00",
        date(2026, 1, 10),
        date(2026, 2, 9),
        date(2026, 1, 22),
    ),
    (
        "AP-002",
        "Energia SA",
        "ENERGIASA00001",
        "8750.00",
        date(2026, 2, 14),
        date(2026, 3, 16),
        date(2026, 2, 20),
    ),
    (
        "AP-003",
        "Logistica Sul LTDA",
        "LOGSUL00000001",
        "12300.00",
        date(2026, 3, 20),
        date(2026, 4, 19),
        date(2026, 3, 28),
    ),
    (
        "AP-004",
        "Software House LTDA",
        "SOFTHOUSE00001",
        "18900.00",
        date(2026, 5, 5),
        date(2026, 6, 4),
        None,
    ),
)


async def _get_or_create_account(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    code: str,
    name: str,
    type_: str,
    nature: str,
) -> Account:
    found = (
        await db.execute(
            select(Account).where(Account.tenant_id == tenant_id, Account.code == code)
        )
    ).scalar_one_or_none()
    if found is not None:
        return found
    account = Account(
        tenant_id=tenant_id,
        code=code,
        name=name,
        type=type_,
        nature=nature,
        allow_posting=True,
        status="active",
    )
    db.add(account)
    await db.flush()
    return account


async def seed_demo(slug: str) -> dict[str, object]:
    """Popula dados de demonstração (AR/AP + pagamentos) para o dashboard.

    Cria plano de contas, período fiscal, entidade legal, faturas e contas a
    pagar (com lançamentos contábeis reais via FinanceService). Idempotente:
    se já houver faturas para o tenant, não duplica.
    """
    async with async_session_maker() as db:
        tenant = (
            await db.execute(select(Tenant).where(Tenant.slug == slug))
        ).scalar_one_or_none()
        if tenant is None:
            raise ValueError(
                f"Tenant '{slug}' nao encontrado. Rode create-owner antes."
            )
        tid = tenant.id
        await set_session_tenant(db, tid)

        already = (
            await db.execute(
                select(func.count())
                .select_from(Invoice)
                .where(Invoice.tenant_id == tid)
            )
        ).scalar() or 0
        if already:
            return {"skipped": True, "invoices": int(already)}

        org = (
            (
                await db.execute(
                    select(Organization).where(Organization.tenant_id == tid)
                )
            )
            .scalars()
            .first()
        )
        if org is None:
            org = Organization(tenant_id=tid, name="Matriz", status="active")
            db.add(org)
            await db.flush()

        entity = (
            (await db.execute(select(LegalEntity).where(LegalEntity.tenant_id == tid)))
            .scalars()
            .first()
        )
        if entity is None:
            entity = LegalEntity(
                tenant_id=tid,
                organization_id=org.id,
                name="Vinicius Comercio e Servicos LTDA",
                trade_name="Vinicius Corp",
                cnpj="VINICIUSME0001",
            )
            db.add(entity)
            await db.flush()

        journal = (
            (await db.execute(select(Journal).where(Journal.tenant_id == tid)))
            .scalars()
            .first()
        )
        if journal is None:
            journal = Journal(tenant_id=tid, name="Diario Geral", code="GERAL")
            db.add(journal)
            await db.flush()

        period = (
            (
                await db.execute(
                    select(FiscalPeriod).where(FiscalPeriod.tenant_id == tid)
                )
            )
            .scalars()
            .first()
        )
        if period is None:
            period = FiscalPeriod(
                tenant_id=tid,
                name="Exercicio 2026",
                start_date=date(2026, 1, 1),
                end_date=date(2026, 12, 31),
                status="open",
            )
            db.add(period)
            await db.flush()

        bank = await _get_or_create_account(
            db, tid, "1.1.1", "Banco / Caixa", "asset", "debit"
        )
        ar = await _get_or_create_account(
            db, tid, "1.1.2", "Clientes a Receber", "asset", "debit"
        )
        ap = await _get_or_create_account(
            db, tid, "2.1.1", "Fornecedores a Pagar", "liability", "credit"
        )
        revenue = await _get_or_create_account(
            db, tid, "3.1.1", "Receita de Vendas", "revenue", "credit"
        )
        expense = await _get_or_create_account(
            db, tid, "4.1.1", "Despesas Operacionais", "expense", "debit"
        )
        equity = await _get_or_create_account(
            db, tid, "3.2.1", "Capital Social", "equity", "credit"
        )

        # Capital inicial: Debito Banco / Credito Capital.
        await FinanceService.create_journal_entry(
            db=db,
            tenant_id=tid,
            entry_date=date(2026, 1, 2),
            journal_id=journal.id,
            description="Integralizacao de capital social",
            lines=[
                {
                    "account_id": bank.id,
                    "amount": Decimal("150000.00"),
                    "direction": "DEBIT",
                },
                {
                    "account_id": equity.id,
                    "amount": Decimal("150000.00"),
                    "direction": "CREDIT",
                },
            ],
            status="posted",
        )

        for number, name, cnpj, amount, issue, due, paid in _DEMO_INVOICES:
            inv = await FinanceService.create_invoice(
                db=db,
                tenant_id=tid,
                legal_entity_id=entity.id,
                customer_name=name,
                cnpj=cnpj,
                number=number,
                amount=Decimal(amount),
                issue_date=issue,
                due_date=due,
                journal_id=journal.id,
                revenue_account_id=revenue.id,
                ar_account_id=ar.id,
            )
            if paid is not None:
                await FinanceService.pay_invoice(
                    db=db,
                    tenant_id=tid,
                    invoice_id=inv.id,
                    amount=Decimal(amount),
                    payment_date=paid,
                    payment_method="PIX",
                    bank_account_info=None,
                    journal_id=journal.id,
                    bank_account_id=bank.id,
                    ar_account_id=ar.id,
                )

        for number, name, cnpj, amount, issue, due, paid in _DEMO_BILLS:
            bill = await FinanceService.create_bill(
                db=db,
                tenant_id=tid,
                legal_entity_id=entity.id,
                provider_name=name,
                cnpj=cnpj,
                number=number,
                amount=Decimal(amount),
                issue_date=issue,
                due_date=due,
                journal_id=journal.id,
                expense_account_id=expense.id,
                ap_account_id=ap.id,
            )
            if paid is not None:
                await FinanceService.pay_bill(
                    db=db,
                    tenant_id=tid,
                    bill_id=bill.id,
                    amount=Decimal(amount),
                    payment_date=paid,
                    payment_method="TED",
                    bank_account_info=None,
                    journal_id=journal.id,
                    bank_account_id=bank.id,
                    ap_account_id=ap.id,
                )

        await db.commit()
        return {
            "skipped": False,
            "invoices": len(_DEMO_INVOICES),
            "bills": len(_DEMO_BILLS),
        }


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
    demo = sub.add_parser("seed-demo", help="Popula dados de demonstracao (AR/AP)")
    demo.add_argument("--slug", required=True)
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

    if args.command == "seed-demo":
        result = asyncio.run(seed_demo(args.slug))
        if result.get("skipped"):
            sys.stdout.write(
                f"Demo ja existe ({result['invoices']} faturas). Nada a fazer.\n"
            )
        else:
            sys.stdout.write(
                f"Demo criada: {result['invoices']} faturas, "
                f"{result['bills']} contas a pagar.\n"
            )
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(_main())

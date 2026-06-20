"""Testes do AnalyticsService — fluxo de caixa (método direto) e KPIs gerenciais.

Rodam em SQLite (mesmo padrão da suíte unitária). Lançamentos são inseridos
diretamente como linhas postadas; faturas/contas e seus pagamentos alimentam o
ageing e o fluxo de caixa.
"""

from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from app.core.database import Base
from app.models.finance import (
    Account,
    Bill,
    BillPayment,
    Invoice,
    InvoicePayment,
    Journal,
    JournalEntry,
    JournalLine,
)
from app.models.tenant import LegalEntity, Organization, Tenant
from app.services.analytics_service import AnalyticsService

PERIOD_START = date(2026, 6, 1)
PERIOD_END = date(2026, 6, 30)


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


@compiles(UUID, "sqlite")
def compile_uuid_sqlite(type_, compiler, **kw):
    return "CHAR(36)"


@pytest_asyncio.fixture(scope="function")
async def db_session():
    for table in Base.metadata.tables.values():
        for c in [c for c in table.constraints if isinstance(c, CheckConstraint)]:
            table.constraints.remove(c)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def base(db_session: AsyncSession):
    tenant = Tenant(
        name="T",
        slug="t-an",
        status="active",
        subscription_price=Decimal("0.00"),
        billing_limit=Decimal("10000.00"),
    )
    db_session.add(tenant)
    await db_session.flush()
    org = Organization(tenant_id=tenant.id, name="Org", status="active")
    db_session.add(org)
    await db_session.flush()
    le = LegalEntity(
        tenant_id=tenant.id,
        organization_id=org.id,
        name="LE",
        cnpj="12345678000199",
    )
    db_session.add(le)
    await db_session.flush()
    journal = Journal(tenant_id=tenant.id, name="Geral", code="GEN")
    db_session.add(journal)
    await db_session.flush()
    return {"tenant": tenant, "org": org, "le": le, "journal": journal}


async def _account(db, tenant_id, code, name, type_, nature) -> Account:
    acc = Account(tenant_id=tenant_id, code=code, name=name, type=type_, nature=nature)
    db.add(acc)
    await db.flush()
    return acc


async def _post(db, tenant_id, journal_id, debit_id, credit_id, amount) -> None:
    je = JournalEntry(
        tenant_id=tenant_id,
        entry_date=date(2026, 6, 15),
        journal_id=journal_id,
        description="lanc",
        status="posted",
    )
    db.add(je)
    await db.flush()
    db.add(
        JournalLine(
            tenant_id=tenant_id,
            journal_entry_id=je.id,
            account_id=debit_id,
            amount=amount,
            direction="DEBIT",
        )
    )
    db.add(
        JournalLine(
            tenant_id=tenant_id,
            journal_entry_id=je.id,
            account_id=credit_id,
            amount=amount,
            direction="CREDIT",
        )
    )
    await db.flush()


@pytest.mark.asyncio
async def test_cash_flow_metodo_direto(db_session: AsyncSession, base: dict):
    tenant = base["tenant"]
    le = base["le"]

    # Faturas com recebimentos no período (entradas) por meio de pagamento.
    inv = Invoice(
        tenant_id=tenant.id,
        legal_entity_id=le.id,
        customer_name="Cliente",
        cnpj="12345678000199",
        number="NF-1",
        amount=Decimal("8000.0000"),
        issue_date=PERIOD_START,
        due_date=PERIOD_END,
        status="partially_paid",
    )
    db_session.add(inv)
    await db_session.flush()
    db_session.add_all(
        [
            InvoicePayment(
                tenant_id=tenant.id,
                invoice_id=inv.id,
                amount=Decimal("6000.0000"),
                payment_date=date(2026, 6, 10),
                payment_method="PIX",
            ),
            InvoicePayment(
                tenant_id=tenant.id,
                invoice_id=inv.id,
                amount=Decimal("2000.0000"),
                payment_date=date(2026, 6, 20),
                payment_method="boleto",
            ),
            # Fora do período: não deve entrar.
            InvoicePayment(
                tenant_id=tenant.id,
                invoice_id=inv.id,
                amount=Decimal("999.0000"),
                payment_date=date(2026, 7, 5),
                payment_method="PIX",
            ),
        ]
    )

    # Conta a pagar com pagamento no período (saída).
    bill = Bill(
        tenant_id=tenant.id,
        legal_entity_id=le.id,
        provider_name="Fornecedor",
        cnpj="98765432000188",
        number="NF-B1",
        amount=Decimal("3000.0000"),
        issue_date=PERIOD_START,
        due_date=PERIOD_END,
        status="partially_paid",
    )
    db_session.add(bill)
    await db_session.flush()
    db_session.add(
        BillPayment(
            tenant_id=tenant.id,
            bill_id=bill.id,
            amount=Decimal("1000.0000"),
            payment_date=date(2026, 6, 12),
            payment_method="TED",
        )
    )
    await db_session.flush()

    cf = await AnalyticsService.get_cash_flow(
        db_session, tenant.id, PERIOD_START, PERIOD_END
    )

    assert cf["operating"]["receipts_from_customers"] == Decimal("8000.0000")
    assert cf["operating"]["payments_to_suppliers"] == Decimal("1000.0000")
    assert cf["operating"]["net_cash_from_operations"] == Decimal("7000.0000")
    assert cf["net_cash_flow"] == Decimal("7000.0000")
    assert cf["by_method"]["inflows"] == {
        "PIX": Decimal("6000.0000"),
        "boleto": Decimal("2000.0000"),
    }
    assert cf["by_method"]["outflows"] == {"TED": Decimal("1000.0000")}


@pytest.mark.asyncio
async def test_cash_flow_datas_invalidas(db_session: AsyncSession, base: dict):
    with pytest.raises(ValueError, match="end_date"):
        await AnalyticsService.get_cash_flow(
            db_session, base["tenant"].id, PERIOD_END, PERIOD_START
        )


@pytest.mark.asyncio
async def test_financial_kpis(db_session: AsyncSession, base: dict):
    tenant = base["tenant"]
    le = base["le"]
    journal = base["journal"]

    caixa = await _account(db_session, tenant.id, "1.1.01", "Caixa", "asset", "debit")
    clientes = await _account(
        db_session, tenant.id, "1.1.02", "Clientes", "asset", "debit"
    )
    fornec = await _account(
        db_session, tenant.id, "2.1.01", "Fornecedores", "liability", "credit"
    )
    capital = await _account(
        db_session, tenant.id, "2.3.01", "Capital", "equity", "credit"
    )
    receita = await _account(
        db_session, tenant.id, "4.1.01", "Receita", "revenue", "credit"
    )
    despesa = await _account(
        db_session, tenant.id, "5.1.01", "Despesa", "expense", "debit"
    )

    # Capital: D Caixa 10000 / C Capital 10000
    await _post(
        db_session, tenant.id, journal.id, caixa.id, capital.id, Decimal("10000")
    )
    # Receita: D Clientes 8000 / C Receita 8000
    await _post(
        db_session, tenant.id, journal.id, clientes.id, receita.id, Decimal("8000")
    )
    # Despesa: D Despesa 3000 / C Fornecedores 3000
    await _post(
        db_session, tenant.id, journal.id, despesa.id, fornec.id, Decimal("3000")
    )

    # AR/AP em aberto (ageing) — faturas/contas pendentes.
    db_session.add(
        Invoice(
            tenant_id=tenant.id,
            legal_entity_id=le.id,
            customer_name="C",
            cnpj="12345678000199",
            number="NF-AR",
            amount=Decimal("8000.0000"),
            issue_date=PERIOD_START,
            due_date=PERIOD_END,
            status="pending",
        )
    )
    db_session.add(
        Bill(
            tenant_id=tenant.id,
            legal_entity_id=le.id,
            provider_name="F",
            cnpj="98765432000188",
            number="NF-AP",
            amount=Decimal("3000.0000"),
            issue_date=PERIOD_START,
            due_date=PERIOD_END,
            status="pending",
        )
    )
    await db_session.flush()

    kpis = await AnalyticsService.get_financial_kpis(
        db_session, tenant.id, PERIOD_START, PERIOD_END
    )

    assert kpis["result"]["gross_revenue"] == Decimal("8000.0000")
    assert kpis["result"]["total_expenses"] == Decimal("3000.0000")
    assert kpis["result"]["net_result"] == Decimal("5000.0000")
    assert kpis["result"]["net_margin"] == Decimal("0.6250")  # 5000/8000

    assert kpis["position"]["total_assets"] == Decimal("18000.0000")  # 10000 + 8000
    assert kpis["position"]["total_liabilities"] == Decimal("3000.0000")
    assert kpis["position"]["total_equity"] == Decimal("10000.0000")
    assert kpis["position"]["debt_ratio"] == Decimal("0.1667")  # 3000/18000
    assert kpis["position"]["equity_ratio"] == Decimal("0.5556")  # 10000/18000

    assert kpis["returns"]["return_on_assets"] == Decimal("0.2778")  # 5000/18000
    assert kpis["returns"]["return_on_equity"] == Decimal("0.5000")  # 5000/10000

    assert kpis["working_capital"]["accounts_receivable_open"] == Decimal("8000.0000")
    assert kpis["working_capital"]["accounts_payable_open"] == Decimal("3000.0000")
    assert kpis["working_capital"]["net_working_capital"] == Decimal("5000.0000")


@pytest.mark.asyncio
async def test_kpis_sem_dados_nao_divide_por_zero(db_session: AsyncSession, base: dict):
    # Tenant sem lançamentos: razões devem ser 0 (sem ZeroDivisionError).
    kpis = await AnalyticsService.get_financial_kpis(
        db_session, base["tenant"].id, PERIOD_START, PERIOD_END
    )
    assert kpis["result"]["net_margin"] == Decimal("0.0000")
    assert kpis["position"]["debt_ratio"] == Decimal("0.0000")
    assert kpis["returns"]["return_on_equity"] == Decimal("0.0000")
    assert kpis["working_capital"]["net_working_capital"] == Decimal("0.0000")

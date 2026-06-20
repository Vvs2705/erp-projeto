"""Testes da conciliação bancária assistida (determinística).

Rodam em SQLite. Linhas de extrato (``BankTransaction``) são casadas com
pagamentos contabilizados (``InvoicePayment``/``BillPayment``) por valor exato e
proximidade de data.
"""

from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import CheckConstraint, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from app.core.database import Base
from app.models.finance import (
    BankTransaction,
    Bill,
    BillPayment,
    Invoice,
    InvoicePayment,
)
from app.models.tenant import LegalEntity, Organization, Tenant
from app.services.reconciliation_service import (
    ReconciliationException,
    ReconciliationService,
)

START = date(2026, 6, 1)
END = date(2026, 6, 30)


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
        slug="t-rec",
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
        tenant_id=tenant.id, organization_id=org.id, name="LE", cnpj="12345678000199"
    )
    db_session.add(le)
    await db_session.flush()
    invoice = Invoice(
        tenant_id=tenant.id,
        legal_entity_id=le.id,
        customer_name="Cliente",
        cnpj="12345678000199",
        number="NF-1",
        amount=Decimal("99999.0000"),
        issue_date=START,
        due_date=END,
        status="partially_paid",
    )
    bill = Bill(
        tenant_id=tenant.id,
        legal_entity_id=le.id,
        provider_name="Fornecedor",
        cnpj="98765432000188",
        number="NF-B1",
        amount=Decimal("99999.0000"),
        issue_date=START,
        due_date=END,
        status="partially_paid",
    )
    db_session.add_all([invoice, bill])
    await db_session.flush()
    return {"tenant": tenant, "invoice": invoice, "bill": bill}


async def _bank_tx(db, tenant_id, amount, tx_date, fitid) -> BankTransaction:
    bt = BankTransaction(
        tenant_id=tenant_id,
        fitid=fitid,
        transaction_date=tx_date,
        amount=Decimal(amount),
        description="extrato",
        reconciled=False,
    )
    db.add(bt)
    await db.flush()
    return bt


async def _inv_payment(
    db, tenant_id, invoice_id, amount, pdate, method
) -> InvoicePayment:
    p = InvoicePayment(
        tenant_id=tenant_id,
        invoice_id=invoice_id,
        amount=Decimal(amount),
        payment_date=pdate,
        payment_method=method,
    )
    db.add(p)
    await db.flush()
    return p


async def _bill_payment(db, tenant_id, bill_id, amount, pdate, method) -> BillPayment:
    p = BillPayment(
        tenant_id=tenant_id,
        bill_id=bill_id,
        amount=Decimal(amount),
        payment_date=pdate,
        payment_method=method,
    )
    db.add(p)
    await db.flush()
    return p


@pytest.mark.asyncio
async def test_suggest_inflow_and_outflow(db_session: AsyncSession, base: dict):
    tenant = base["tenant"]
    # Entrada: bank +1000 casa com recebimento de 1000.
    bt_in = await _bank_tx(db_session, tenant.id, "1000.0000", date(2026, 6, 10), "F1")
    pay_in = await _inv_payment(
        db_session, tenant.id, base["invoice"].id, "1000.0000", date(2026, 6, 11), "PIX"
    )
    # Saída: bank -500 casa com pagamento de 500.
    bt_out = await _bank_tx(db_session, tenant.id, "-500.0000", date(2026, 6, 12), "F2")
    pay_out = await _bill_payment(
        db_session, tenant.id, base["bill"].id, "500.0000", date(2026, 6, 12), "TED"
    )

    sug = await ReconciliationService.suggest_matches(db_session, tenant.id, START, END)
    by_bt = {s["bank_transaction"]["id"]: s for s in sug}

    in_cands = by_bt[bt_in.id]["candidates"]
    assert len(in_cands) == 1
    assert in_cands[0]["kind"] == "invoice_payment"
    assert in_cands[0]["payment_id"] == pay_in.id

    out_cands = by_bt[bt_out.id]["candidates"]
    assert len(out_cands) == 1
    assert out_cands[0]["kind"] == "bill_payment"
    assert out_cands[0]["payment_id"] == pay_out.id


@pytest.mark.asyncio
async def test_suggest_exclui_fora_da_tolerancia(db_session: AsyncSession, base: dict):
    tenant = base["tenant"]
    bt = await _bank_tx(db_session, tenant.id, "1000.0000", date(2026, 6, 10), "F1")
    # Pagamento a 10 dias de distância, tolerância padrão 3 -> sem candidato.
    await _inv_payment(
        db_session, tenant.id, base["invoice"].id, "1000.0000", date(2026, 6, 20), "PIX"
    )
    sug = await ReconciliationService.suggest_matches(db_session, tenant.id, START, END)
    assert sug[0]["bank_transaction"]["id"] == bt.id
    assert sug[0]["candidates"] == []


@pytest.mark.asyncio
async def test_confirm_persiste_vinculo(db_session: AsyncSession, base: dict):
    tenant = base["tenant"]
    bt = await _bank_tx(db_session, tenant.id, "1000.0000", date(2026, 6, 10), "F1")
    pay = await _inv_payment(
        db_session, tenant.id, base["invoice"].id, "1000.0000", date(2026, 6, 10), "PIX"
    )
    result = await ReconciliationService.confirm_match(
        db_session, tenant.id, bt.id, "invoice_payment", pay.id
    )
    assert result.reconciled is True
    assert result.matched_kind == "invoice_payment"
    assert result.matched_payment_id == pay.id

    refreshed = (
        await db_session.execute(
            select(BankTransaction).where(BankTransaction.id == bt.id)
        )
    ).scalar_one()
    assert refreshed.reconciled is True


@pytest.mark.asyncio
async def test_confirm_rejeita_sinal_errado(db_session: AsyncSession, base: dict):
    tenant = base["tenant"]
    bt = await _bank_tx(db_session, tenant.id, "1000.0000", date(2026, 6, 10), "F1")
    pay = await _bill_payment(
        db_session, tenant.id, base["bill"].id, "1000.0000", date(2026, 6, 10), "TED"
    )
    # Entrada (+) não pode casar com bill_payment.
    with pytest.raises(ReconciliationException):
        await ReconciliationService.confirm_match(
            db_session, tenant.id, bt.id, "bill_payment", pay.id
        )


@pytest.mark.asyncio
async def test_confirm_rejeita_valor_divergente(db_session: AsyncSession, base: dict):
    tenant = base["tenant"]
    bt = await _bank_tx(db_session, tenant.id, "1000.0000", date(2026, 6, 10), "F1")
    pay = await _inv_payment(
        db_session, tenant.id, base["invoice"].id, "900.0000", date(2026, 6, 10), "PIX"
    )
    with pytest.raises(ReconciliationException):
        await ReconciliationService.confirm_match(
            db_session, tenant.id, bt.id, "invoice_payment", pay.id
        )


@pytest.mark.asyncio
async def test_confirm_rejeita_pagamento_ja_usado(db_session: AsyncSession, base: dict):
    tenant = base["tenant"]
    pay = await _inv_payment(
        db_session, tenant.id, base["invoice"].id, "1000.0000", date(2026, 6, 10), "PIX"
    )
    bt1 = await _bank_tx(db_session, tenant.id, "1000.0000", date(2026, 6, 10), "F1")
    bt2 = await _bank_tx(db_session, tenant.id, "1000.0000", date(2026, 6, 10), "F2")
    await ReconciliationService.confirm_match(
        db_session, tenant.id, bt1.id, "invoice_payment", pay.id
    )
    with pytest.raises(ReconciliationException):
        await ReconciliationService.confirm_match(
            db_session, tenant.id, bt2.id, "invoice_payment", pay.id
        )


@pytest.mark.asyncio
async def test_auto_reconcile_so_candidato_unico(db_session: AsyncSession, base: dict):
    tenant = base["tenant"]
    # bt_unico: 700 com um único recebimento de 700 -> auto.
    await _bank_tx(db_session, tenant.id, "700.0000", date(2026, 6, 5), "F1")
    await _inv_payment(
        db_session, tenant.id, base["invoice"].id, "700.0000", date(2026, 6, 5), "PIX"
    )
    # bt_ambiguo: 1000 com DOIS recebimentos de 1000 -> não concilia (manual).
    await _bank_tx(db_session, tenant.id, "1000.0000", date(2026, 6, 6), "F2")
    await _inv_payment(
        db_session, tenant.id, base["invoice"].id, "1000.0000", date(2026, 6, 6), "PIX"
    )
    await _inv_payment(
        db_session,
        tenant.id,
        base["invoice"].id,
        "1000.0000",
        date(2026, 6, 7),
        "boleto",
    )

    result = await ReconciliationService.auto_reconcile(
        db_session, tenant.id, START, END
    )
    assert result["unreconciled"] == 2
    assert result["auto_reconciled"] == 1
    assert result["pending"] == 1

    # Sobra exatamente uma linha não conciliada.
    remaining = (
        (
            await db_session.execute(
                select(BankTransaction).where(
                    BankTransaction.tenant_id == tenant.id,
                    BankTransaction.reconciled.is_(False),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(remaining) == 1

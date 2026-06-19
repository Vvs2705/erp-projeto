"""Testes do serviço de apuração RTC (CBS/IBS) — sem mocks, SQLite em memória.

Cobrem a persistência de tributos por documento (``record_document_taxes`` /
``determine_and_record``) e a apuração por período (``assess_period``):
débito - crédito, valor a recolher, crédito a transportar e janela de datas.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from fiscal_engine import Operation, Regime
from sqlalchemy import CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from app.core.database import Base
from app.models.tenant import Tenant
from app.services.fiscal_apuracao_service import (
    FiscalApuracaoException,
    FiscalApuracaoService,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


@compiles(UUID, "sqlite")
def _compile_uuid_sqlite(type_, compiler, **kw):
    return "CHAR(36)"


@pytest_asyncio.fixture(scope="function")
async def db_session():
    # PG CheckConstraints não compilam em SQLite — removidos da metadata.
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
async def tenant_id(db_session: AsyncSession) -> uuid.UUID:
    tenant = Tenant(
        name="Apuração Tenant",
        slug="apuracao-tenant",
        status="active",
        subscription_price=Decimal("0.00"),
        billing_limit=Decimal("10000.00"),
    )
    db_session.add(tenant)
    await db_session.flush()
    return tenant.id


# 2026: CBS 0,9% e IBS 0,1% (fase de teste da RTC).
JUN_2026 = date(2026, 6, 15)
PERIOD_START = date(2026, 6, 1)
PERIOD_END = date(2026, 6, 30)


@pytest.mark.asyncio
async def test_determine_and_record_persiste_linhas(
    db_session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    doc_id = uuid.uuid4()
    rows = await FiscalApuracaoService.determine_and_record(
        db_session,
        tenant_id,
        document_type="sale",
        document_id=doc_id,
        document_number="NF-001",
        direction="debit",
        base=Decimal("1000.00"),
        issue_date=JUN_2026,
        operation=Operation.SALE_GOODS,
        regime=Regime.PRESUMIDO,
    )

    by_tax = {r.tax: r for r in rows}
    # Mercadoria + lucro presumido + RTC 2026.
    assert by_tax["cbs"].amount == Decimal("9.00")  # 1000 * 0.009
    assert by_tax["ibs"].amount == Decimal("1.00")  # 1000 * 0.001
    assert by_tax["icms"].amount == Decimal("180.00")
    assert by_tax["cbs"].direction == "debit"
    assert by_tax["cbs"].document_number == "NF-001"
    assert by_tax["cbs"].document_id == doc_id


@pytest.mark.asyncio
async def test_assess_period_debito_menos_credito(
    db_session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    # Saída (débito) base 1000 e entrada (crédito) base 400.
    await FiscalApuracaoService.determine_and_record(
        db_session,
        tenant_id,
        document_type="sale",
        document_id=uuid.uuid4(),
        document_number="NF-SAIDA",
        direction="debit",
        base=Decimal("1000.00"),
        issue_date=JUN_2026,
    )
    await FiscalApuracaoService.determine_and_record(
        db_session,
        tenant_id,
        document_type="purchase",
        document_id=uuid.uuid4(),
        document_number="NF-ENTRADA",
        direction="credit",
        base=Decimal("400.00"),
        issue_date=JUN_2026,
    )

    result = await FiscalApuracaoService.assess_period(
        db_session, tenant_id, PERIOD_START, PERIOD_END
    )

    cbs = result["taxes"]["cbs"]
    assert cbs["debit"] == Decimal("9.00")
    assert cbs["credit"] == Decimal("3.60")  # 400 * 0.009
    assert cbs["balance"] == Decimal("5.40")
    assert cbs["payable"] == Decimal("5.40")
    assert cbs["credit_carryforward"] == Decimal("0.00")

    ibs = result["taxes"]["ibs"]
    assert ibs["payable"] == Decimal("0.60")  # 1.00 - 0.40

    assert result["total_payable"] == Decimal("6.00")


@pytest.mark.asyncio
async def test_assess_period_saldo_credor_transporta(
    db_session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    # Crédito maior que débito → nada a recolher, saldo credor a transportar.
    await FiscalApuracaoService.determine_and_record(
        db_session,
        tenant_id,
        document_type="sale",
        document_id=uuid.uuid4(),
        document_number="NF-SAIDA",
        direction="debit",
        base=Decimal("100.00"),
        issue_date=JUN_2026,
    )
    await FiscalApuracaoService.determine_and_record(
        db_session,
        tenant_id,
        document_type="purchase",
        document_id=uuid.uuid4(),
        document_number="NF-ENTRADA",
        direction="credit",
        base=Decimal("1000.00"),
        issue_date=JUN_2026,
    )

    result = await FiscalApuracaoService.assess_period(
        db_session, tenant_id, PERIOD_START, PERIOD_END
    )

    cbs = result["taxes"]["cbs"]
    assert cbs["balance"] == Decimal("-8.10")  # 0.90 - 9.00
    assert cbs["payable"] == Decimal("0.00")
    assert cbs["credit_carryforward"] == Decimal("8.10")
    assert result["total_payable"] == Decimal("0.00")


@pytest.mark.asyncio
async def test_assess_period_ignora_fora_da_janela(
    db_session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    # Documento de maio não entra na apuração de junho.
    await FiscalApuracaoService.determine_and_record(
        db_session,
        tenant_id,
        document_type="sale",
        document_id=uuid.uuid4(),
        document_number="NF-MAIO",
        direction="debit",
        base=Decimal("1000.00"),
        issue_date=date(2026, 5, 31),
    )

    result = await FiscalApuracaoService.assess_period(
        db_session, tenant_id, PERIOD_START, PERIOD_END
    )
    assert result["taxes"]["cbs"]["debit"] == Decimal("0.00")
    assert result["total_payable"] == Decimal("0.00")


@pytest.mark.asyncio
async def test_record_direction_invalida_levanta(
    db_session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    with pytest.raises(FiscalApuracaoException):
        await FiscalApuracaoService.determine_and_record(
            db_session,
            tenant_id,
            document_type="sale",
            document_id=uuid.uuid4(),
            document_number="NF-X",
            direction="saida",  # inválido
            base=Decimal("100.00"),
            issue_date=JUN_2026,
        )


@pytest.mark.asyncio
async def test_assess_period_intervalo_invalido_levanta(
    db_session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    with pytest.raises(FiscalApuracaoException):
        await FiscalApuracaoService.assess_period(
            db_session, tenant_id, PERIOD_END, PERIOD_START
        )

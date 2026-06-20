"""Testes da valoração de estoque por LOTE (PEPS/FIFO) e por SÉRIE (id. específica).

Rodam em SQLite (sem RLS/triggers, como o restante da suíte unitária). As
``CheckConstraint`` específicas do Postgres são removidas dos metadados para que
o DDL compile no SQLite — mesmo padrão de ``test_inventory_service.py``.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import CheckConstraint, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from app.core.database import Base
from app.models.inventory import Product, StockLot, StockSerial
from app.models.tenant import Organization, Tenant
from app.services.inventory_service import (
    InsufficientStockException,
    InventoryService,
    LotTrackingException,
    SerialTrackingException,
)


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


async def _make_product(db: AsyncSession, tracking_mode: str) -> tuple:
    tenant = Tenant(
        name="T",
        slug=f"t-{tracking_mode}",
        status="active",
        subscription_price=Decimal("0.00"),
        billing_limit=Decimal("10000.00"),
    )
    db.add(tenant)
    await db.flush()
    org = Organization(tenant_id=tenant.id, name="Org", status="active")
    db.add(org)
    await db.flush()
    product = Product(
        tenant_id=tenant.id,
        sku=f"SKU-{tracking_mode}",
        name="P",
        unit_of_measure="UN",
        tracking_mode=tracking_mode,
    )
    db.add(product)
    await db.flush()
    return tenant, org, product


# --------------------------- LOTE / PEPS (FIFO) ---------------------------


@pytest.mark.asyncio
async def test_lot_fifo_consome_mais_antigo_primeiro(db_session: AsyncSession):
    tenant, org, product = await _make_product(db_session, "lot")

    # Lote A: 10 @ 100 (entra primeiro)
    await InventoryService.register_stock_move(
        db=db_session,
        tenant_id=tenant.id,
        organization_id=org.id,
        product_id=product.id,
        move_type="in",
        quantity=Decimal("10.0000"),
        unit_cost=Decimal("100.0000"),
        reference="NF-1",
        lot_number="LOTE-A",
    )
    # Lote B: 10 @ 130 (entra depois)
    await InventoryService.register_stock_move(
        db=db_session,
        tenant_id=tenant.id,
        organization_id=org.id,
        product_id=product.id,
        move_type="in",
        quantity=Decimal("10.0000"),
        unit_cost=Decimal("130.0000"),
        reference="NF-2",
        lot_number="LOTE-B",
    )

    val = await InventoryService.get_or_create_valuation(
        db_session, tenant.id, product.id
    )
    assert val.qty_on_hand == Decimal("20.0000")
    assert val.total_value == Decimal("2300.0000")

    # Saída de 15 sem indicar lote -> FIFO: 10 de A (1000) + 5 de B (650) = 1650
    out = await InventoryService.register_stock_move(
        db=db_session,
        tenant_id=tenant.id,
        organization_id=org.id,
        product_id=product.id,
        move_type="out",
        quantity=Decimal("15.0000"),
        unit_cost=Decimal("0.0000"),
        reference="NF-V1",
    )
    assert out.total_cost == Decimal("1650.0000")
    assert out.unit_cost == Decimal("110.0000")  # 1650 / 15

    val = await InventoryService.get_or_create_valuation(
        db_session, tenant.id, product.id
    )
    assert val.qty_on_hand == Decimal("5.0000")
    assert val.total_value == Decimal("650.0000")  # resta 5 de B @ 130

    lots = {
        lot.lot_number: lot
        for lot in (
            await db_session.execute(
                select(StockLot).where(StockLot.product_id == product.id)
            )
        )
        .scalars()
        .all()
    }
    assert lots["LOTE-A"].qty_on_hand == Decimal("0.0000")
    assert lots["LOTE-B"].qty_on_hand == Decimal("5.0000")


@pytest.mark.asyncio
async def test_lot_fifo_prioriza_validade_mais_proxima(db_session: AsyncSession):
    tenant, org, product = await _make_product(db_session, "lot")
    today = date.today()

    # Lote NOVO entra primeiro, mas vence depois.
    await InventoryService.register_stock_move(
        db=db_session,
        tenant_id=tenant.id,
        organization_id=org.id,
        product_id=product.id,
        move_type="in",
        quantity=Decimal("5.0000"),
        unit_cost=Decimal("200.0000"),
        reference="NF-1",
        lot_number="VENCE-DEPOIS",
        expiry_date=today + timedelta(days=60),
    )
    # Lote que vence ANTES (entra depois) -> deve sair primeiro.
    await InventoryService.register_stock_move(
        db=db_session,
        tenant_id=tenant.id,
        organization_id=org.id,
        product_id=product.id,
        move_type="in",
        quantity=Decimal("5.0000"),
        unit_cost=Decimal("300.0000"),
        reference="NF-2",
        lot_number="VENCE-ANTES",
        expiry_date=today + timedelta(days=10),
    )

    out = await InventoryService.register_stock_move(
        db=db_session,
        tenant_id=tenant.id,
        organization_id=org.id,
        product_id=product.id,
        move_type="out",
        quantity=Decimal("5.0000"),
        unit_cost=Decimal("0.0000"),
        reference="NF-V1",
    )
    # Consumiu o lote de validade mais próxima (300), não o que entrou primeiro.
    assert out.total_cost == Decimal("1500.0000")


@pytest.mark.asyncio
async def test_lot_out_lote_especifico(db_session: AsyncSession):
    tenant, org, product = await _make_product(db_session, "lot")
    for ln, cost in (("LOTE-A", "100.0000"), ("LOTE-B", "130.0000")):
        await InventoryService.register_stock_move(
            db=db_session,
            tenant_id=tenant.id,
            organization_id=org.id,
            product_id=product.id,
            move_type="in",
            quantity=Decimal("10.0000"),
            unit_cost=Decimal(cost),
            reference="NF",
            lot_number=ln,
        )

    # Saída indicando explicitamente o LOTE-B (mais novo/caro).
    out = await InventoryService.register_stock_move(
        db=db_session,
        tenant_id=tenant.id,
        organization_id=org.id,
        product_id=product.id,
        move_type="out",
        quantity=Decimal("4.0000"),
        unit_cost=Decimal("0.0000"),
        reference="NF-V",
        lot_number="LOTE-B",
    )
    assert out.total_cost == Decimal("520.0000")  # 4 @ 130


@pytest.mark.asyncio
async def test_lot_in_exige_lot_number(db_session: AsyncSession):
    tenant, org, product = await _make_product(db_session, "lot")
    with pytest.raises(LotTrackingException):
        await InventoryService.register_stock_move(
            db=db_session,
            tenant_id=tenant.id,
            organization_id=org.id,
            product_id=product.id,
            move_type="in",
            quantity=Decimal("1.0000"),
            unit_cost=Decimal("10.0000"),
            reference="NF",
        )


@pytest.mark.asyncio
async def test_lot_out_insuficiente(db_session: AsyncSession):
    tenant, org, product = await _make_product(db_session, "lot")
    await InventoryService.register_stock_move(
        db=db_session,
        tenant_id=tenant.id,
        organization_id=org.id,
        product_id=product.id,
        move_type="in",
        quantity=Decimal("3.0000"),
        unit_cost=Decimal("10.0000"),
        reference="NF",
        lot_number="LOTE-A",
    )
    with pytest.raises(InsufficientStockException):
        await InventoryService.register_stock_move(
            db=db_session,
            tenant_id=tenant.id,
            organization_id=org.id,
            product_id=product.id,
            move_type="out",
            quantity=Decimal("5.0000"),
            unit_cost=Decimal("0.0000"),
            reference="NF-V",
        )


@pytest.mark.asyncio
async def test_lot_reentrada_mesmo_lote_media_ponderada(db_session: AsyncSession):
    tenant, org, product = await _make_product(db_session, "lot")
    # Mesmo lote recebido duas vezes a custos diferentes.
    await InventoryService.register_stock_move(
        db=db_session,
        tenant_id=tenant.id,
        organization_id=org.id,
        product_id=product.id,
        move_type="in",
        quantity=Decimal("10.0000"),
        unit_cost=Decimal("100.0000"),
        reference="NF-1",
        lot_number="LOTE-A",
    )
    await InventoryService.register_stock_move(
        db=db_session,
        tenant_id=tenant.id,
        organization_id=org.id,
        product_id=product.id,
        move_type="in",
        quantity=Decimal("10.0000"),
        unit_cost=Decimal("120.0000"),
        reference="NF-2",
        lot_number="LOTE-A",
    )
    lot = (
        await db_session.execute(
            select(StockLot).where(StockLot.lot_number == "LOTE-A")
        )
    ).scalar_one()
    assert lot.qty_on_hand == Decimal("20.0000")
    assert lot.unit_cost == Decimal("110.0000")  # (1000 + 1200) / 20


# --------------------------- SÉRIE / id. específica ---------------------------


@pytest.mark.asyncio
async def test_serial_identificacao_especifica(db_session: AsyncSession):
    tenant, org, product = await _make_product(db_session, "serial")

    # Entrada de 3 séries @ 500.
    await InventoryService.register_stock_move(
        db=db_session,
        tenant_id=tenant.id,
        organization_id=org.id,
        product_id=product.id,
        move_type="in",
        quantity=Decimal("3.0000"),
        unit_cost=Decimal("500.0000"),
        reference="NF-1",
        serial_numbers=["S1", "S2", "S3"],
    )
    val = await InventoryService.get_or_create_valuation(
        db_session, tenant.id, product.id
    )
    assert val.qty_on_hand == Decimal("3.0000")
    assert val.total_value == Decimal("1500.0000")

    # Saída das séries S1 e S3 (identificação específica).
    out = await InventoryService.register_stock_move(
        db=db_session,
        tenant_id=tenant.id,
        organization_id=org.id,
        product_id=product.id,
        move_type="out",
        quantity=Decimal("2.0000"),
        unit_cost=Decimal("0.0000"),
        reference="NF-V",
        serial_numbers=["S1", "S3"],
    )
    assert out.total_cost == Decimal("1000.0000")

    rows = {
        s.serial_number: s.status
        for s in (
            await db_session.execute(
                select(StockSerial).where(StockSerial.product_id == product.id)
            )
        )
        .scalars()
        .all()
    }
    assert rows == {"S1": "consumed", "S2": "in_stock", "S3": "consumed"}


@pytest.mark.asyncio
async def test_serial_in_quantidade_incompativel(db_session: AsyncSession):
    tenant, org, product = await _make_product(db_session, "serial")
    with pytest.raises(SerialTrackingException):
        await InventoryService.register_stock_move(
            db=db_session,
            tenant_id=tenant.id,
            organization_id=org.id,
            product_id=product.id,
            move_type="in",
            quantity=Decimal("3.0000"),
            unit_cost=Decimal("500.0000"),
            reference="NF",
            serial_numbers=["S1", "S2"],  # só 2 para qty 3
        )


@pytest.mark.asyncio
async def test_serial_out_serie_indisponivel(db_session: AsyncSession):
    tenant, org, product = await _make_product(db_session, "serial")
    await InventoryService.register_stock_move(
        db=db_session,
        tenant_id=tenant.id,
        organization_id=org.id,
        product_id=product.id,
        move_type="in",
        quantity=Decimal("1.0000"),
        unit_cost=Decimal("500.0000"),
        reference="NF",
        serial_numbers=["S1"],
    )
    with pytest.raises(SerialTrackingException):
        await InventoryService.register_stock_move(
            db=db_session,
            tenant_id=tenant.id,
            organization_id=org.id,
            product_id=product.id,
            move_type="out",
            quantity=Decimal("1.0000"),
            unit_cost=Decimal("0.0000"),
            reference="NF-V",
            serial_numbers=["INEXISTENTE"],
        )


# --------------------------- coerência de modo ---------------------------


@pytest.mark.asyncio
async def test_modo_none_rejeita_lote(db_session: AsyncSession):
    tenant, org, product = await _make_product(db_session, "none")
    with pytest.raises(LotTrackingException):
        await InventoryService.register_stock_move(
            db=db_session,
            tenant_id=tenant.id,
            organization_id=org.id,
            product_id=product.id,
            move_type="in",
            quantity=Decimal("1.0000"),
            unit_cost=Decimal("10.0000"),
            reference="NF",
            lot_number="LOTE-X",
        )


@pytest.mark.asyncio
async def test_modo_none_rejeita_serie(db_session: AsyncSession):
    tenant, org, product = await _make_product(db_session, "none")
    with pytest.raises(SerialTrackingException):
        await InventoryService.register_stock_move(
            db=db_session,
            tenant_id=tenant.id,
            organization_id=org.id,
            product_id=product.id,
            move_type="in",
            quantity=Decimal("1.0000"),
            unit_cost=Decimal("10.0000"),
            reference="NF",
            serial_numbers=["S1"],
        )

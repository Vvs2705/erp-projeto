import pytest
import pytest_asyncio
import uuid
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.core.database import Base
from app.models.tenant import Tenant, Organization, LegalEntity
from app.models.finance import FiscalPeriod, Journal, Account, JournalEntry, Bill, Invoice
from app.models.inventory import Product, StockMove, StockValuation
from app.models.purchase import PurchaseOrder, PurchaseOrderItem
from app.models.sales import SalesOrder, SalesOrderItem

from app.services.inventory_service import InventoryService, InsufficientStockException
from app.services.purchase_service import PurchaseService
from app.services.sales_service import SalesService

from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB, UUID

@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"

@compiles(UUID, "sqlite")
def compile_uuid_sqlite(type_, compiler, **kw):
    return "CHAR(36)"

# Register a custom REGEXP function for SQLite to handle postgres `~` checks
def sqlite_regexp(expr, item):
    if item is None:
        return False
    return re.search(expr, item) is not None

@pytest_asyncio.fixture(scope="function")
async def db_session():
    # In-memory SQLite for complete, mockless DB tests
    # We strip PG-specific CheckConstraints from metadata so SQLite DDL compilation succeeds
    from sqlalchemy import CheckConstraint
    for table in Base.metadata.tables.values():
        to_remove = [c for c in table.constraints if isinstance(c, CheckConstraint)]
        for c in to_remove:
            table.constraints.remove(c)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def my_on_connect(dbapi_con, connection_record):
        dbapi_con.create_function("regexp", 2, sqlite_regexp)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session_maker = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session_maker() as session:
        yield session

    await engine.dispose()

@pytest_asyncio.fixture
async def seed_data(db_session: AsyncSession):
    # 1. Create Tenant
    tenant = Tenant(
        name="Test Tenant",
        slug="test-tenant",
        status="active",
        subscription_price=Decimal("0.00"),
        billing_limit=Decimal("10000.00")
    )
    db_session.add(tenant)
    await db_session.flush()

    # 2. Create Organization
    org = Organization(
        tenant_id=tenant.id,
        name="Test Org",
        status="active"
    )
    db_session.add(org)
    await db_session.flush()

    # 3. Create Legal Entity
    le = LegalEntity(
        tenant_id=tenant.id,
        organization_id=org.id,
        name="Test Legal Entity",
        cnpj="12345678000199"
    )
    db_session.add(le)
    await db_session.flush()

    # 4. Create Product
    product = Product(
        tenant_id=tenant.id,
        sku="SKU-PROD-001",
        name="Test Product",
        unit_of_measure="UN"
    )
    db_session.add(product)
    await db_session.flush()

    # 5. Create Fiscal Period
    fiscal_period = FiscalPeriod(
        tenant_id=tenant.id,
        name="2026-06",
        start_date=date.today() - timedelta(days=5),
        end_date=date.today() + timedelta(days=25),
        status="open"
    )
    db_session.add(fiscal_period)
    await db_session.flush()

    # 6. Create Journal
    journal = Journal(
        tenant_id=tenant.id,
        name="General Journal",
        code="GEN"
    )
    db_session.add(journal)
    await db_session.flush()

    # 7. Create Accounts
    stock_acc = Account(tenant_id=tenant.id, code="1.1.03.001", name="Estoque de Mercadorias", type="asset")
    ap_acc = Account(tenant_id=tenant.id, code="2.1.01.001", name="Fornecedores a Pagar", type="liability")
    ar_acc = Account(tenant_id=tenant.id, code="1.1.02.001", name="Clientes a Receber", type="asset")
    revenue_acc = Account(tenant_id=tenant.id, code="4.1.01.001", name="Receita de Vendas", type="revenue")
    cmv_acc = Account(tenant_id=tenant.id, code="5.1.02.001", name="Custo das Mercadorias Vendidas (CMV)", type="expense")

    db_session.add_all([stock_acc, ap_acc, ar_acc, revenue_acc, cmv_acc])
    await db_session.flush()

    return {
        "tenant": tenant,
        "org": org,
        "le": le,
        "product": product,
        "fiscal_period": fiscal_period,
        "journal": journal,
        "stock_acc": stock_acc,
        "ap_acc": ap_acc,
        "ar_acc": ar_acc,
        "revenue_acc": revenue_acc,
        "cmv_acc": cmv_acc
    }

@pytest.mark.asyncio
async def test_moving_average_logic(db_session: AsyncSession, seed_data: dict):
    tenant = seed_data["tenant"]
    org = seed_data["org"]
    product = seed_data["product"]

    # 1. First Entry: 10 units @ 100.00
    move1 = await InventoryService.register_stock_move(
        db=db_session,
        tenant_id=tenant.id,
        organization_id=org.id,
        product_id=product.id,
        move_type="in",
        quantity=Decimal("10.0000"),
        unit_cost=Decimal("100.0000"),
        reference="NF-001"
    )
    assert move1.total_cost == Decimal("1000.0000")

    val = await InventoryService.get_or_create_valuation(db_session, tenant.id, product.id)
    assert val.qty_on_hand == Decimal("10.0000")
    assert val.average_unit_cost == Decimal("100.0000")
    assert val.total_value == Decimal("1000.0000")

    # 2. Second Entry: 5 units @ 130.00
    move2 = await InventoryService.register_stock_move(
        db=db_session,
        tenant_id=tenant.id,
        organization_id=org.id,
        product_id=product.id,
        move_type="in",
        quantity=Decimal("5.0000"),
        unit_cost=Decimal("130.0000"),
        reference="NF-002"
    )
    assert move2.total_cost == Decimal("650.0000")

    # MPM = (1000 + 650) / (10 + 5) = 1650 / 15 = 110.00
    val = await InventoryService.get_or_create_valuation(db_session, tenant.id, product.id)
    assert val.qty_on_hand == Decimal("15.0000")
    assert val.average_unit_cost == Decimal("110.0000")
    assert val.total_value == Decimal("1650.0000")

    # 3. First Dispatch: 6 units
    move3 = await InventoryService.register_stock_move(
        db=db_session,
        tenant_id=tenant.id,
        organization_id=org.id,
        product_id=product.id,
        move_type="out",
        quantity=Decimal("6.0000"),
        unit_cost=Decimal("0.0000"),  # Out cost is determined automatically by MPM
        reference="NF-V001"
    )
    # Unit cost of the move must be the current average cost (110.00)
    assert move3.unit_cost == Decimal("110.0000")
    assert move3.total_cost == Decimal("660.0000")

    val = await InventoryService.get_or_create_valuation(db_session, tenant.id, product.id)
    assert val.qty_on_hand == Decimal("9.0000")
    assert val.average_unit_cost == Decimal("110.0000")
    assert val.total_value == Decimal("990.0000")

    # 4. Try to dispatch more than available (9 units available, try 10)
    with pytest.raises(InsufficientStockException):
        await InventoryService.register_stock_move(
            db=db_session,
            tenant_id=tenant.id,
            organization_id=org.id,
            product_id=product.id,
            move_type="out",
            quantity=Decimal("10.0000"),
            unit_cost=Decimal("0.0000"),
            reference="NF-V002"
        )

@pytest.mark.asyncio
async def test_purchase_order_receipt_posting_rules(db_session: AsyncSession, seed_data: dict):
    tenant = seed_data["tenant"]
    org = seed_data["org"]
    le = seed_data["le"]
    product = seed_data["product"]
    journal = seed_data["journal"]
    stock_acc = seed_data["stock_acc"]
    ap_acc = seed_data["ap_acc"]

    # 1. Create and Approve Purchase Order
    po = await PurchaseService.create_purchase_order(
        db=db_session,
        tenant_id=tenant.id,
        provider_name="Supplier Alpha",
        cnpj="98765432100099",
        items=[
            {"product_id": product.id, "quantity": Decimal("20.0000"), "unit_cost": Decimal("50.0000")}
        ]
    )
    po = await PurchaseService.approve_purchase_order(db_session, tenant.id, po.id)

    # 2. Receive items: 12 units
    bill = await PurchaseService.receive_purchase_order_items(
        db=db_session,
        tenant_id=tenant.id,
        purchase_order_id=po.id,
        items_received={product.id: Decimal("12.0000")},
        invoice_number="NF-PUR-100",
        organization_id=org.id,
        legal_entity_id=le.id,
        journal_id=journal.id,
        stock_account_id=stock_acc.id,
        ap_account_id=ap_acc.id
    )

    # Assert Bill was created correctly
    assert bill.provider_name == "Supplier Alpha"
    assert bill.cnpj == "98765432100099"
    assert bill.amount == Decimal("600.0000")  # 12 units * 50.00
    assert bill.status == "pending"

    # Assert stock move registered
    val = await InventoryService.get_or_create_valuation(db_session, tenant.id, product.id)
    assert val.qty_on_hand == Decimal("12.0000")
    assert val.average_unit_cost == Decimal("50.0000")
    assert val.total_value == Decimal("600.0000")

    # Assert JournalEntry provision was created and posted:
    # Debit: Estoque (600.00)
    # Credit: Fornecedores a Pagar (600.00)
    stmt = select(JournalEntry).where(JournalEntry.tenant_id == tenant.id)
    res = await db_session.execute(stmt)
    entries = res.scalars().all()
    assert len(entries) == 1
    
    je = entries[0]
    assert je.status == "posted"
    assert len(je.lines) == 2
    
    debit_line = next(line for line in je.lines if line.direction == "DEBIT")
    credit_line = next(line for line in je.lines if line.direction == "CREDIT")

    assert debit_line.account_id == stock_acc.id
    assert debit_line.amount == Decimal("600.0000")
    assert credit_line.account_id == ap_acc.id
    assert credit_line.amount == Decimal("600.0000")

@pytest.mark.asyncio
async def test_sales_order_dispatch_posting_rules(db_session: AsyncSession, seed_data: dict):
    tenant = seed_data["tenant"]
    org = seed_data["org"]
    le = seed_data["le"]
    product = seed_data["product"]
    journal = seed_data["journal"]
    stock_acc = seed_data["stock_acc"]
    ar_acc = seed_data["ar_acc"]
    revenue_acc = seed_data["revenue_acc"]
    cmv_acc = seed_data["cmv_acc"]

    # 1. Establish initial stock to allow dispatch
    # Stock: 10 units @ 80.00 = 800.00
    await InventoryService.register_stock_move(
        db=db_session,
        tenant_id=tenant.id,
        organization_id=org.id,
        product_id=product.id,
        move_type="in",
        quantity=Decimal("10.0000"),
        unit_cost=Decimal("80.0000"),
        reference="INITIAL-STOCK"
    )

    # 2. Create and Approve Sales Order
    # Order: 4 units @ 150.00 each
    so = await SalesService.create_sales_order(
        db=db_session,
        tenant_id=tenant.id,
        customer_name="Customer Beta",
        cnpj="44555666000188",
        items=[
            {"product_id": product.id, "quantity": Decimal("4.0000"), "unit_price": Decimal("150.0000")}
        ]
    )
    so = await SalesService.approve_sales_order(db_session, tenant.id, so.id)

    # 3. Dispatch items: 4 units
    invoice = await SalesService.dispatch_sales_order_items(
        db=db_session,
        tenant_id=tenant.id,
        sales_order_id=so.id,
        items_dispatched={product.id: Decimal("4.0000")},
        invoice_number="NF-SLS-500",
        organization_id=org.id,
        legal_entity_id=le.id,
        journal_id=journal.id,
        cmv_account_id=cmv_acc.id,
        stock_account_id=stock_acc.id,
        ar_account_id=ar_acc.id,
        revenue_account_id=revenue_acc.id
    )

    # Assert Invoice created correctly
    assert invoice.customer_name == "Customer Beta"
    assert invoice.cnpj == "44555666000188"
    assert invoice.amount == Decimal("600.0000")  # 4 units * 150.00
    assert invoice.status == "pending"

    # Assert stock move registered & updated valuation:
    # Remaining stock: 6 units @ 80.00 = 480.00
    val = await InventoryService.get_or_create_valuation(db_session, tenant.id, product.id)
    assert val.qty_on_hand == Decimal("6.0000")
    assert val.average_unit_cost == Decimal("80.0000")
    assert val.total_value == Decimal("480.0000")

    # Assert two JournalEntries created and posted:
    # 1. CMV Journal Entry (Debit CMV 320.00, Credit Stock 320.00) (4 units * 80.00 MPM)
    # 2. Sales Revenue Journal Entry (Debit AR 600.00, Credit Revenue 600.00) (4 units * 150.00 price)
    stmt = select(JournalEntry).where(JournalEntry.tenant_id == tenant.id).order_by(JournalEntry.created_at.asc())
    res = await db_session.execute(stmt)
    entries = res.scalars().all()
    
    # Note: 1st entry is the initial stock input provision (if any, wait: register_stock_move doesn't post journal entry, it only registers stock. Wait, does it? No, register_stock_move doesn't post journal entries by itself. Only receive_purchase_order_items and dispatch_sales_order_items post journal entries. So there should be exactly 2 entries in total: CMV and Venda!)
    assert len(entries) == 2

    # Check CMV entry:
    cmv_je = next(entry for entry in entries if "CMV" in entry.description)
    assert cmv_je.status == "posted"
    assert len(cmv_je.lines) == 2
    cmv_debit = next(line for line in cmv_je.lines if line.direction == "DEBIT")
    cmv_credit = next(line for line in cmv_je.lines if line.direction == "CREDIT")
    assert cmv_debit.account_id == cmv_acc.id
    assert cmv_debit.amount == Decimal("320.0000")  # 4 * 80
    assert cmv_credit.account_id == stock_acc.id
    assert cmv_credit.amount == Decimal("320.0000")

    # Check Sales Revenue entry:
    sales_je = next(entry for entry in entries if "Faturamento" in entry.description)
    assert sales_je.status == "posted"
    assert len(sales_je.lines) == 2
    sales_debit = next(line for line in sales_je.lines if line.direction == "DEBIT")
    sales_credit = next(line for line in sales_je.lines if line.direction == "CREDIT")
    assert sales_debit.account_id == ar_acc.id
    assert sales_debit.amount == Decimal("600.0000")  # 4 * 150
    assert sales_credit.account_id == revenue_acc.id
    assert sales_credit.amount == Decimal("600.0000")

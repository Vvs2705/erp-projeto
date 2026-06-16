import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional, Dict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales import SalesQuotation, SalesOrder, SalesOrderItem
from app.models.finance import Invoice, Journal, Account
from app.models.tenant import LegalEntity
from app.services.inventory_service import InventoryService
from app.services.finance_service import FinanceService

class SalesException(Exception):
    """Base exception for sales service"""
    pass

class SalesOrderNotFoundException(SalesException):
    pass

class SalesOrderItemNotFoundException(SalesException):
    pass

class SalesService:
    @staticmethod
    async def create_quotation(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        customer_name: str,
        cnpj: str,
        items: list[dict]
    ) -> SalesQuotation:
        """
        Creates a Sales Quotation.
        Each item in `items` should have keys: product_id, quantity, unit_price.
        """
        total_amount = Decimal("0.0000")
        for item in items:
            qty = Decimal(str(item["quantity"]))
            price = Decimal(str(item["unit_price"]))
            total_amount += qty * price

        quotation = SalesQuotation(
            tenant_id=tenant_id,
            customer_name=customer_name,
            cnpj=cnpj,
            status="draft",
            total_amount=total_amount
        )
        db.add(quotation)
        await db.flush()
        return quotation

    @staticmethod
    async def create_sales_order(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        customer_name: str,
        cnpj: str,
        items: list[dict]
    ) -> SalesOrder:
        """
        Creates a Sales Order with its items.
        Each item in `items` should have keys: product_id, quantity, unit_price.
        """
        total_amount = Decimal("0.0000")
        so_items = []
        for item in items:
            qty = Decimal(str(item["quantity"]))
            price = Decimal(str(item["unit_price"]))
            total_amount += qty * price
            so_items.append(
                SalesOrderItem(
                    tenant_id=tenant_id,
                    product_id=uuid.UUID(str(item["product_id"])),
                    quantity=qty,
                    unit_price=price,
                    quantity_dispatched=Decimal("0.0000")
                )
            )

        so = SalesOrder(
            tenant_id=tenant_id,
            customer_name=customer_name,
            cnpj=cnpj,
            status="draft",
            total_amount=total_amount,
            items=so_items
        )
        db.add(so)
        await db.flush()
        return so

    @staticmethod
    async def approve_sales_order(
        db: AsyncSession, tenant_id: uuid.UUID, sales_order_id: uuid.UUID
    ) -> SalesOrder:
        stmt = select(SalesOrder).where(
            SalesOrder.tenant_id == tenant_id,
            SalesOrder.id == sales_order_id
        )
        res = await db.execute(stmt)
        so = res.scalar_one_or_none()
        if not so:
            raise SalesOrderNotFoundException(f"Sales order {sales_order_id} not found.")
        so.status = "approved"
        await db.flush()
        return so

    @staticmethod
    async def dispatch_sales_order_items(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        sales_order_id: uuid.UUID,
        items_dispatched: dict[uuid.UUID, Decimal],
        invoice_number: str,
        organization_id: Optional[uuid.UUID] = None,
        legal_entity_id: Optional[uuid.UUID] = None,
        journal_id: Optional[uuid.UUID] = None,
        cmv_account_id: Optional[uuid.UUID] = None,
        stock_account_id: Optional[uuid.UUID] = None,
        ar_account_id: Optional[uuid.UUID] = None,
        revenue_account_id: Optional[uuid.UUID] = None
    ) -> Invoice:
        """
        Processes dispatch of SO items:
        1. Updates quantity_dispatched on SalesOrderItem.
        2. Calls register_stock_move(move_type='out') for each item, retrieving its MPM value.
        3. Generates CMV JournalEntry: Debit CMV Account (Expense) and Credit Stock Account (Asset).
        4. Creates an Invoice (Contas a Receber) for the sales revenue.
        5. Generates Sales JournalEntry: Debit AR Account (Asset) and Credit Revenue Account (Revenue).
        """
        # Fetch Sales Order
        so_stmt = select(SalesOrder).where(
            SalesOrder.tenant_id == tenant_id,
            SalesOrder.id == sales_order_id
        )
        so_res = await db.execute(so_stmt)
        so = so_res.scalar_one_or_none()
        if not so:
            raise SalesOrderNotFoundException(f"Sales order {sales_order_id} not found.")

        if so.status != "approved":
            raise SalesException(f"Sales order must be approved before dispatching. Current status: {so.status}")

        # Resolve organization_id if not provided
        if not organization_id:
            from app.models.tenant import Organization
            org_stmt = select(Organization).where(Organization.tenant_id == tenant_id)
            org_res = await db.execute(org_stmt)
            org = org_res.scalar()
            if not org:
                raise SalesException("No organization found for tenant. Cannot process dispatch.")
            organization_id = org.id

        # Resolve legal_entity_id if not provided
        if not legal_entity_id:
            le_stmt = select(LegalEntity).where(LegalEntity.tenant_id == tenant_id)
            le_res = await db.execute(le_stmt)
            le = le_res.scalar()
            if not le:
                raise SalesException("No legal entity found for tenant. Cannot process dispatch.")
            legal_entity_id = le.id

        total_cmv_value = Decimal("0.0000")
        total_sales_revenue = Decimal("0.0000")

        # Process each dispatched item
        for prod_id, qty in items_dispatched.items():
            qty_dec = Decimal(str(qty))
            if qty_dec <= Decimal("0.0000"):
                continue

            # Find matching item in SO
            matched_item = None
            for item in so.items:
                if item.product_id == prod_id:
                    matched_item = item
                    break

            if not matched_item:
                raise SalesOrderItemNotFoundException(
                    f"Product {prod_id} is not part of Sales Order {sales_order_id}."
                )

            # Update quantity dispatched
            matched_item.quantity_dispatched += qty_dec
            total_sales_revenue += qty_dec * matched_item.unit_price

            # Call register_stock_move (out). It calculates average cost automatically.
            stock_move = await InventoryService.register_stock_move(
                db=db,
                tenant_id=tenant_id,
                organization_id=organization_id,
                product_id=prod_id,
                move_type="out",
                quantity=qty_dec,
                unit_cost=Decimal("0.0000"),
                reference=f"SO-DISP-{invoice_number}"
            )
            # Accumulate the actual MPM cost
            total_cmv_value += stock_move.total_cost

        if total_sales_revenue <= Decimal("0.0000"):
            raise SalesException("No valid items to dispatch or dispatched quantities are zero.")

        # Update SO status to dispatched if all items fully dispatched
        fully_dispatched = True
        for item in so.items:
            if item.quantity_dispatched < item.quantity:
                fully_dispatched = False
                break
        if fully_dispatched:
            so.status = "dispatched"

        # Resolve accounts and journal
        if not journal_id:
            j_stmt = select(Journal).where(Journal.tenant_id == tenant_id)
            j_res = await db.execute(j_stmt)
            journal = j_res.scalar()
            if not journal:
                journal = Journal(tenant_id=tenant_id, name="Vendas", code="VEND")
                db.add(journal)
                await db.flush()
            journal_id = journal.id

        if not stock_account_id:
            sa_stmt = select(Account).where(Account.tenant_id == tenant_id, Account.type == "asset", Account.name.ilike("%estoque%"))
            sa_res = await db.execute(sa_stmt)
            sa = sa_res.scalar()
            if not sa:
                sa = Account(tenant_id=tenant_id, code="1.1.03.001", name="Estoque de Mercadorias", type="asset")
                db.add(sa)
                await db.flush()
            stock_account_id = sa.id

        if not cmv_account_id:
            cmv_stmt = select(Account).where(Account.tenant_id == tenant_id, Account.type == "expense", Account.name.ilike("%cmv%"))
            cmv_res = await db.execute(cmv_stmt)
            cmv = cmv_res.scalar()
            if not cmv:
                cmv = Account(tenant_id=tenant_id, code="5.1.02.001", name="Custo das Mercadorias Vendidas (CMV)", type="expense")
                db.add(cmv)
                await db.flush()
            cmv_account_id = cmv.id

        if not ar_account_id:
            ar_stmt = select(Account).where(Account.tenant_id == tenant_id, Account.type == "asset", (Account.name.ilike("%receber%") | Account.name.ilike("%clientes%")))
            ar_res = await db.execute(ar_stmt)
            ar = ar_res.scalar()
            if not ar:
                ar = Account(tenant_id=tenant_id, code="1.1.02.001", name="Clientes a Receber", type="asset")
                db.add(ar)
                await db.flush()
            ar_account_id = ar.id

        if not revenue_account_id:
            rev_stmt = select(Account).where(Account.tenant_id == tenant_id, Account.type == "revenue", Account.name.ilike("%vendas%"))
            rev_res = await db.execute(rev_stmt)
            rev = rev_res.scalar()
            if not rev:
                rev = Account(tenant_id=tenant_id, code="4.1.01.001", name="Receita de Vendas", type="revenue")
                db.add(rev)
                await db.flush()
            revenue_account_id = rev.id

        # 1. Post CMV Journal Entry (Debit CMV, Credit Estoque)
        if total_cmv_value > Decimal("0.0000"):
            cmv_lines = [
                {
                    "account_id": cmv_account_id,
                    "amount": total_cmv_value,
                    "direction": "DEBIT",
                    "description": f"CMV - Despacho NF {invoice_number}"
                },
                {
                    "account_id": stock_account_id,
                    "amount": total_cmv_value,
                    "direction": "CREDIT",
                    "description": f"Baixa Estoque - Despacho NF {invoice_number}"
                }
            ]
            await FinanceService.create_journal_entry(
                db=db,
                tenant_id=tenant_id,
                entry_date=date.today(),
                journal_id=journal_id,
                description=f"CMV Despacho NF-{invoice_number}",
                lines=cmv_lines,
                status="posted"
            )

        # 2. Post Sales Journal Entry (Debit AR, Credit Revenue)
        sales_lines = [
            {
                "account_id": ar_account_id,
                "amount": total_sales_revenue,
                "direction": "DEBIT",
                "description": f"AR Clientes - Venda NF {invoice_number}"
            },
            {
                "account_id": revenue_account_id,
                "amount": total_sales_revenue,
                "direction": "CREDIT",
                "description": f"Receita Vendas - Venda NF {invoice_number}"
            }
        ]
        await FinanceService.create_journal_entry(
            db=db,
            tenant_id=tenant_id,
            entry_date=date.today(),
            journal_id=journal_id,
            description=f"Faturamento Venda NF-{invoice_number}",
            lines=sales_lines,
            status="posted"
        )

        # 3. Create the Invoice (Contas a Receber)
        invoice = Invoice(
            tenant_id=tenant_id,
            legal_entity_id=legal_entity_id,
            customer_name=so.customer_name,
            cnpj=so.cnpj,
            number=invoice_number,
            amount=total_sales_revenue,
            issue_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            status="pending"
        )
        db.add(invoice)
        await db.flush()

        return invoice

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finance import Account, Bill, Journal
from app.models.purchase import PurchaseOrder, PurchaseOrderItem, PurchaseRequisition
from app.models.tenant import LegalEntity
from app.services.finance_service import FinanceService
from app.services.inventory_service import InventoryService


class PurchaseException(Exception):
    """Base exception for purchase service"""

    pass


class PurchaseOrderNotFoundException(PurchaseException):
    pass


class PurchaseOrderItemNotFoundException(PurchaseException):
    pass


class PurchaseService:
    @staticmethod
    async def create_requisition(
        db: AsyncSession, tenant_id: uuid.UUID, description: str
    ) -> PurchaseRequisition:
        req = PurchaseRequisition(
            tenant_id=tenant_id, description=description, status="draft"
        )
        db.add(req)
        await db.flush()
        return req

    @staticmethod
    async def approve_requisition(
        db: AsyncSession, tenant_id: uuid.UUID, requisition_id: uuid.UUID
    ) -> PurchaseRequisition:
        stmt = select(PurchaseRequisition).where(
            PurchaseRequisition.tenant_id == tenant_id,
            PurchaseRequisition.id == requisition_id,
        )
        res = await db.execute(stmt)
        req = res.scalar_one_or_none()
        if not req:
            raise PurchaseException(f"Purchase requisition {requisition_id} not found.")
        req.status = "approved"
        await db.flush()
        return req

    @staticmethod
    async def create_purchase_order(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        provider_name: str,
        cnpj: str,
        items: list[dict[str, Any]],
    ) -> PurchaseOrder:
        """
        Creates a Purchase Order with its items.
        Each item in `items` should have keys: product_id, quantity, unit_cost.
        Calculates the total_amount automatically.
        """
        total_amount = Decimal("0.0000")
        po_items = []
        for item in items:
            qty = Decimal(str(item["quantity"]))
            cost = Decimal(str(item["unit_cost"]))
            total_amount += qty * cost
            po_items.append(
                PurchaseOrderItem(
                    tenant_id=tenant_id,
                    product_id=uuid.UUID(str(item["product_id"])),
                    quantity=qty,
                    unit_cost=cost,
                    quantity_received=Decimal("0.0000"),
                )
            )

        po = PurchaseOrder(
            tenant_id=tenant_id,
            provider_name=provider_name,
            cnpj=cnpj,
            status="draft",
            total_amount=total_amount,
            items=po_items,
        )
        db.add(po)
        await db.flush()
        return po

    @staticmethod
    async def approve_purchase_order(
        db: AsyncSession, tenant_id: uuid.UUID, purchase_order_id: uuid.UUID
    ) -> PurchaseOrder:
        stmt = select(PurchaseOrder).where(
            PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.id == purchase_order_id
        )
        res = await db.execute(stmt)
        po = res.scalar_one_or_none()
        if not po:
            raise PurchaseOrderNotFoundException(
                f"Purchase order {purchase_order_id} not found."
            )
        po.status = "approved"
        await db.flush()
        return po

    @staticmethod
    async def receive_purchase_order_items(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        purchase_order_id: uuid.UUID,
        items_received: dict[uuid.UUID, Decimal],
        invoice_number: str,
        organization_id: uuid.UUID | None = None,
        legal_entity_id: uuid.UUID | None = None,
        journal_id: uuid.UUID | None = None,
        stock_account_id: uuid.UUID | None = None,
        ap_account_id: uuid.UUID | None = None,
    ) -> Bill:
        """
        Processes receipt of PO items:
        1. Updates quantity_received on PurchaseOrderItem.
        2. Calls register_stock_move(move_type='in') for each item.
        3. Creates a Bill (Contas a Pagar) for the received items value.
        4. Posts JournalEntry: Debit Stock Account (Asset) and Credit AP Account
           (Liability).
        """
        # Fetch the Purchase Order with items
        po_stmt = select(PurchaseOrder).where(
            PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.id == purchase_order_id
        )
        po_res = await db.execute(po_stmt)
        po = po_res.scalar_one_or_none()
        if not po:
            raise PurchaseOrderNotFoundException(
                f"Purchase order {purchase_order_id} not found."
            )

        if po.status != "approved":
            raise PurchaseException(
                "Purchase order must be approved before receiving. "
                f"Current status: {po.status}"
            )

        # Resolve organization_id if not provided
        if not organization_id:
            # Let's fetch the first organization for this tenant
            from app.models.tenant import Organization

            org_stmt = select(Organization).where(Organization.tenant_id == tenant_id)
            org_res = await db.execute(org_stmt)
            org = org_res.scalar()
            if not org:
                raise PurchaseException(
                    "No organization found for tenant. Cannot process receipt."
                )
            organization_id = org.id

        # Resolve legal_entity_id if not provided
        if not legal_entity_id:
            le_stmt = select(LegalEntity).where(LegalEntity.tenant_id == tenant_id)
            le_res = await db.execute(le_stmt)
            le = le_res.scalar()
            if not le:
                raise PurchaseException(
                    "No legal entity found for tenant. Cannot process receipt."
                )
            legal_entity_id = le.id

        total_received_value = Decimal("0.0000")

        # Process each received item
        for prod_id, qty in items_received.items():
            qty_dec = Decimal(str(qty))
            if qty_dec <= Decimal("0.0000"):
                continue

            # Find matching item in PO
            matched_item = None
            for item in po.items:
                if item.product_id == prod_id:
                    matched_item = item
                    break

            if not matched_item:
                raise PurchaseOrderItemNotFoundException(
                    f"Product {prod_id} is not part of Purchase Order "
                    f"{purchase_order_id}."
                )

            # Update quantity received
            matched_item.quantity_received += qty_dec
            total_received_value += qty_dec * matched_item.unit_cost

            # Call register_stock_move
            await InventoryService.register_stock_move(
                db=db,
                tenant_id=tenant_id,
                organization_id=organization_id,
                product_id=prod_id,
                move_type="in",
                quantity=qty_dec,
                unit_cost=matched_item.unit_cost,
                reference=f"PO-REC-{invoice_number}",
            )

        if total_received_value <= Decimal("0.0000"):
            raise PurchaseException(
                "No valid items to receive or received quantities are zero."
            )

        # Update PO status to received if all items fully received
        fully_received = True
        for item in po.items:
            if item.quantity_received < item.quantity:
                fully_received = False
                break
        if fully_received:
            po.status = "received"

        # Resolve account details or find/create them
        if not journal_id:
            j_stmt = select(Journal).where(Journal.tenant_id == tenant_id)
            j_res = await db.execute(j_stmt)
            journal = j_res.scalar()
            if not journal:
                journal = Journal(tenant_id=tenant_id, name="Compras", code="COMP")
                db.add(journal)
                await db.flush()
            journal_id = journal.id

        if not stock_account_id:
            sa_stmt = select(Account).where(
                Account.tenant_id == tenant_id,
                Account.type == "asset",
                Account.name.ilike("%estoque%"),
            )
            sa_res = await db.execute(sa_stmt)
            sa = sa_res.scalar()
            if not sa:
                sa = Account(
                    tenant_id=tenant_id,
                    code="1.1.03.001",
                    name="Estoque de Mercadorias",
                    type="asset",
                )
                db.add(sa)
                await db.flush()
            stock_account_id = sa.id

        if not ap_account_id:
            ap_stmt = select(Account).where(
                Account.tenant_id == tenant_id,
                Account.type == "liability",
                Account.name.ilike("%fornecedores%"),
            )
            ap_res = await db.execute(ap_stmt)
            ap = ap_res.scalar()
            if not ap:
                ap = Account(
                    tenant_id=tenant_id,
                    code="2.1.01.001",
                    name="Fornecedores a Pagar",
                    type="liability",
                )
                db.add(ap)
                await db.flush()
            ap_account_id = ap.id

        # 1. Create provision Journal Entry (Partida Dobrada)
        # Debit: Stock Account (Asset)
        # Credit: AP Account (Liability)
        lines = [
            {
                "account_id": stock_account_id,
                "amount": total_received_value,
                "direction": "DEBIT",
                "description": f"Debito Estoque - Rec. NF {invoice_number}",
            },
            {
                "account_id": ap_account_id,
                "amount": total_received_value,
                "direction": "CREDIT",
                "description": f"Credito Fornecedores - Rec. NF {invoice_number}",
            },
        ]

        await FinanceService.create_journal_entry(
            db=db,
            tenant_id=tenant_id,
            entry_date=date.today(),
            journal_id=journal_id,
            description=f"Recebimento de Mercadorias NF-{invoice_number}",
            lines=lines,
            status="posted",
        )

        # 2. Create the Bill (Contas a Pagar)
        bill = Bill(
            tenant_id=tenant_id,
            legal_entity_id=legal_entity_id,
            provider_name=po.provider_name,
            cnpj=po.cnpj,
            number=invoice_number,
            amount=total_received_value,
            issue_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            status="pending",
        )
        db.add(bill)
        await db.flush()

        return bill

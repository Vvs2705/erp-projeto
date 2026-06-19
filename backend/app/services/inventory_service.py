import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inventory import Product, StockMove, StockValuation


class InventoryException(Exception):
    """Base exception for inventory service"""

    pass


class InsufficientStockException(InventoryException):
    pass


class ProductNotFoundException(InventoryException):
    pass


class InventoryService:
    @staticmethod
    async def get_or_create_valuation(
        db: AsyncSession, tenant_id: uuid.UUID, product_id: uuid.UUID
    ) -> StockValuation:
        stmt = select(StockValuation).where(
            StockValuation.tenant_id == tenant_id,
            StockValuation.product_id == product_id,
        )
        res = await db.execute(stmt)
        val = res.scalar_one_or_none()
        if not val:
            val = StockValuation(
                tenant_id=tenant_id,
                product_id=product_id,
                qty_on_hand=Decimal("0.0000"),
                average_unit_cost=Decimal("0.0000"),
                total_value=Decimal("0.0000"),
            )
            db.add(val)
            await db.flush()
        return val

    @staticmethod
    async def register_stock_move(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        organization_id: uuid.UUID,
        product_id: uuid.UUID,
        move_type: str,
        quantity: Decimal,
        unit_cost: Decimal,
        reference: str,
    ) -> StockMove:
        """
        Registers a stock movement, updates the stock valuation using MPM, and
        saves both records.
        """
        # Validate product exists
        prod_stmt = select(Product).where(
            Product.tenant_id == tenant_id, Product.id == product_id
        )
        prod_res = await db.execute(prod_stmt)
        if not prod_res.scalar_one_or_none():
            raise ProductNotFoundException(f"Product with ID {product_id} not found.")

        # Ensure correct type
        qty = Decimal(str(quantity))
        u_cost = Decimal(str(unit_cost))

        if qty <= Decimal("0.0000"):
            raise InventoryException("Quantity must be greater than zero.")

        # Fetch or create stock valuation
        valuation = await InventoryService.get_or_create_valuation(
            db, tenant_id, product_id
        )

        actual_unit_cost = u_cost
        if move_type == "in":
            valuation.qty_on_hand += qty
            valuation.total_value += qty * u_cost
            if valuation.qty_on_hand > Decimal("0.0000"):
                valuation.average_unit_cost = (
                    valuation.total_value / valuation.qty_on_hand
                )
            else:
                valuation.average_unit_cost = Decimal("0.0000")
            total_cost = qty * u_cost
        elif move_type == "out":
            if valuation.qty_on_hand < qty:
                raise InsufficientStockException(
                    f"Insufficient stock for product {product_id}. "
                    f"Available: {valuation.qty_on_hand}, Requested: {qty}"
                )
            actual_unit_cost = valuation.average_unit_cost
            valuation.qty_on_hand -= qty
            valuation.total_value -= qty * actual_unit_cost
            total_cost = qty * actual_unit_cost
        else:
            raise InventoryException(
                f"Invalid move_type: {move_type}. Must be 'in' or 'out'."
            )

        # Create stock move
        stock_move = StockMove(
            tenant_id=tenant_id,
            organization_id=organization_id,
            product_id=product_id,
            move_type=move_type,
            quantity=qty,
            unit_cost=actual_unit_cost,
            total_cost=total_cost,
            reference=reference,
        )
        db.add(stock_move)
        await db.flush()

        return stock_move

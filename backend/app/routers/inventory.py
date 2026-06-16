import uuid
from decimal import Decimal
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db, set_session_tenant
from app.core.security import get_current_tenant_and_user
from app.models.inventory import Product
from app.services.inventory_service import InventoryService, InventoryException, InsufficientStockException

router = APIRouter(prefix="/api/v1/inventory", tags=["Inventory"])

class ProductCreate(BaseModel):
    sku: str = Field(..., max_length=100)
    name: str = Field(..., max_length=255)
    unit_of_measure: str = Field(..., max_length=50)

class StockMoveCreate(BaseModel):
    product_id: uuid.UUID
    move_type: str = Field(..., pattern="^(in|out)$")
    quantity: Decimal = Field(..., gt=0, decimal_places=4)
    unit_cost: Decimal = Field(..., ge=0, decimal_places=4)
    reference: str = Field(..., max_length=255)

@router.post("/products", status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreate,
    db: AsyncSession = Depends(get_db),
    tenant_and_user: tuple[uuid.UUID, uuid.UUID] = Depends(get_current_tenant_and_user)
):
    tenant_id, _ = tenant_and_user
    await set_session_tenant(db, tenant_id)
    try:
        # Check if SKU already exists for this tenant
        existing_stmt = select(Product).where(Product.tenant_id == tenant_id, Product.sku == payload.sku)
        existing_res = await db.execute(existing_stmt)
        if existing_res.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="SKU already exists for this tenant.")

        product = Product(
            tenant_id=tenant_id,
            sku=payload.sku,
            name=payload.name,
            unit_of_measure=payload.unit_of_measure
        )
        db.add(product)
        await db.commit()
        return {
            "id": product.id,
            "sku": product.sku,
            "name": product.name,
            "unit_of_measure": product.unit_of_measure
        }
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")

@router.post("/stock-movements", status_code=status.HTTP_201_CREATED)
async def register_stock_movement(
    payload: StockMoveCreate,
    db: AsyncSession = Depends(get_db),
    tenant_and_user: tuple[uuid.UUID, uuid.UUID] = Depends(get_current_tenant_and_user)
):
    tenant_id, _ = tenant_and_user
    await set_session_tenant(db, tenant_id)
    try:
        # Resolve organization_id (using default organization lookup or similar)
        from app.models.tenant import Organization
        org_stmt = select(Organization).where(Organization.tenant_id == tenant_id)
        org_res = await db.execute(org_stmt)
        org = org_res.scalar()
        if not org:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No organization found for tenant.")

        stock_move = await InventoryService.register_stock_move(
            db=db,
            tenant_id=tenant_id,
            organization_id=org.id,
            product_id=payload.product_id,
            move_type=payload.move_type,
            quantity=payload.quantity,
            unit_cost=payload.unit_cost,
            reference=payload.reference
        )
        await db.commit()
        return {
            "id": stock_move.id,
            "product_id": stock_move.product_id,
            "move_type": stock_move.move_type,
            "quantity": stock_move.quantity,
            "unit_cost": stock_move.unit_cost,
            "total_cost": stock_move.total_cost,
            "reference": stock_move.reference
        }
    except InsufficientStockException as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except InventoryException as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")

@router.get("/stock-valuations/{product_id}")
async def get_stock_valuation(
    product_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_and_user: tuple[uuid.UUID, uuid.UUID] = Depends(get_current_tenant_and_user)
):
    tenant_id, _ = tenant_and_user
    await set_session_tenant(db, tenant_id)
    try:
        valuation = await InventoryService.get_or_create_valuation(db, tenant_id, product_id)
        return {
            "product_id": valuation.product_id,
            "qty_on_hand": valuation.qty_on_hand,
            "average_unit_cost": valuation.average_unit_cost,
            "total_value": valuation.total_value
        }
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")

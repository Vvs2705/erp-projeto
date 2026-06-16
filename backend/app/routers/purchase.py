import uuid
import re
from decimal import Decimal
from typing import Optional, List, Dict
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, set_session_tenant
from app.core.security import get_current_tenant_and_user
from app.services.purchase_service import PurchaseService, PurchaseException, PurchaseOrderNotFoundException

router = APIRouter(prefix="/api/v1/purchase", tags=["Purchase"])

class RequisitionCreate(BaseModel):
    description: str = Field(..., max_length=255)

class OrderItemSchema(BaseModel):
    product_id: uuid.UUID
    quantity: Decimal = Field(..., gt=0, decimal_places=4)
    unit_cost: Decimal = Field(..., ge=0, decimal_places=4)

class PurchaseOrderCreate(BaseModel):
    provider_name: str = Field(..., max_length=255)
    cnpj: str = Field(..., description="14 character alphanumeric/numeric CNPJ")
    items: List[OrderItemSchema] = Field(..., min_length=1)

    @field_validator("cnpj")
    @classmethod
    def validate_cnpj(cls, v: str) -> str:
        if not re.match(r"^[A-Z0-9]{14}$", v):
            raise ValueError("CNPJ must be exactly 14 alphanumeric uppercase characters.")
        return v

class ReceivePOItemsRequest(BaseModel):
    items_received: Dict[uuid.UUID, Decimal]
    invoice_number: str = Field(..., max_length=255)
    organization_id: Optional[uuid.UUID] = None
    legal_entity_id: Optional[uuid.UUID] = None
    journal_id: Optional[uuid.UUID] = None
    stock_account_id: Optional[uuid.UUID] = None
    ap_account_id: Optional[uuid.UUID] = None

@router.post("/requisitions", status_code=status.HTTP_201_CREATED)
async def create_requisition(
    payload: RequisitionCreate,
    db: AsyncSession = Depends(get_db),
    tenant_and_user: tuple[uuid.UUID, uuid.UUID] = Depends(get_current_tenant_and_user)
):
    tenant_id, _ = tenant_and_user
    await set_session_tenant(db, tenant_id)
    try:
        req = await PurchaseService.create_requisition(db, tenant_id, payload.description)
        await db.commit()
        return {
            "id": req.id,
            "description": req.description,
            "status": req.status
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")

@router.post("/requisitions/{requisition_id}/approve")
async def approve_requisition(
    requisition_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_and_user: tuple[uuid.UUID, uuid.UUID] = Depends(get_current_tenant_and_user)
):
    tenant_id, _ = tenant_and_user
    await set_session_tenant(db, tenant_id)
    try:
        req = await PurchaseService.approve_requisition(db, tenant_id, requisition_id)
        await db.commit()
        return {
            "id": req.id,
            "description": req.description,
            "status": req.status
        }
    except PurchaseException as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")

@router.post("/orders", status_code=status.HTTP_201_CREATED)
async def create_purchase_order(
    payload: PurchaseOrderCreate,
    db: AsyncSession = Depends(get_db),
    tenant_and_user: tuple[uuid.UUID, uuid.UUID] = Depends(get_current_tenant_and_user)
):
    tenant_id, _ = tenant_and_user
    await set_session_tenant(db, tenant_id)
    try:
        items_dict = [item.model_dump() for item in payload.items]
        po = await PurchaseService.create_purchase_order(
            db=db,
            tenant_id=tenant_id,
            provider_name=payload.provider_name,
            cnpj=payload.cnpj,
            items=items_dict
        )
        await db.commit()
        return {
            "id": po.id,
            "provider_name": po.provider_name,
            "cnpj": po.cnpj,
            "status": po.status,
            "total_amount": po.total_amount
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")

@router.post("/orders/{purchase_order_id}/approve")
async def approve_purchase_order(
    purchase_order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_and_user: tuple[uuid.UUID, uuid.UUID] = Depends(get_current_tenant_and_user)
):
    tenant_id, _ = tenant_and_user
    await set_session_tenant(db, tenant_id)
    try:
        po = await PurchaseService.approve_purchase_order(db, tenant_id, purchase_order_id)
        await db.commit()
        return {
            "id": po.id,
            "provider_name": po.provider_name,
            "status": po.status
        }
    except PurchaseOrderNotFoundException as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")

@router.post("/orders/{purchase_order_id}/receive", status_code=status.HTTP_201_CREATED)
async def receive_purchase_order_items(
    purchase_order_id: uuid.UUID,
    payload: ReceivePOItemsRequest,
    db: AsyncSession = Depends(get_db),
    tenant_and_user: tuple[uuid.UUID, uuid.UUID] = Depends(get_current_tenant_and_user)
):
    tenant_id, _ = tenant_and_user
    await set_session_tenant(db, tenant_id)
    try:
        bill = await PurchaseService.receive_purchase_order_items(
            db=db,
            tenant_id=tenant_id,
            purchase_order_id=purchase_order_id,
            items_received=payload.items_received,
            invoice_number=payload.invoice_number,
            organization_id=payload.organization_id,
            legal_entity_id=payload.legal_entity_id,
            journal_id=payload.journal_id,
            stock_account_id=payload.stock_account_id,
            ap_account_id=payload.ap_account_id
        )
        await db.commit()
        return {
            "id": bill.id,
            "provider_name": bill.provider_name,
            "number": bill.number,
            "amount": bill.amount,
            "status": bill.status
        }
    except PurchaseOrderNotFoundException as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PurchaseException as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")

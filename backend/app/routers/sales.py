import re
import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, set_session_tenant
from app.core.security import get_current_tenant_and_user
from app.services.sales_service import (
    SalesException,
    SalesOrderNotFoundException,
    SalesService,
)

router = APIRouter(prefix="/api/v1/sales", tags=["Sales"])


class SalesItemSchema(BaseModel):
    product_id: uuid.UUID
    quantity: Decimal = Field(..., gt=0, decimal_places=4)
    unit_price: Decimal = Field(..., ge=0, decimal_places=4)


class SalesQuotationCreate(BaseModel):
    customer_name: str = Field(..., max_length=255)
    cnpj: str = Field(..., description="14 character alphanumeric/numeric CNPJ")
    items: list[SalesItemSchema] = Field(..., min_length=1)

    @field_validator("cnpj")
    @classmethod
    def validate_cnpj(cls, v: str) -> str:
        if not re.match(r"^[A-Z0-9]{14}$", v):
            raise ValueError(
                "CNPJ must be exactly 14 alphanumeric uppercase characters."
            )
        return v


class SalesOrderCreate(BaseModel):
    customer_name: str = Field(..., max_length=255)
    cnpj: str = Field(..., description="14 character alphanumeric/numeric CNPJ")
    items: list[SalesItemSchema] = Field(..., min_length=1)

    @field_validator("cnpj")
    @classmethod
    def validate_cnpj(cls, v: str) -> str:
        if not re.match(r"^[A-Z0-9]{14}$", v):
            raise ValueError(
                "CNPJ must be exactly 14 alphanumeric uppercase characters."
            )
        return v


class DispatchSOItemsRequest(BaseModel):
    items_dispatched: dict[uuid.UUID, Decimal]
    invoice_number: str = Field(..., max_length=255)
    organization_id: uuid.UUID | None = None
    legal_entity_id: uuid.UUID | None = None
    journal_id: uuid.UUID | None = None
    cmv_account_id: uuid.UUID | None = None
    stock_account_id: uuid.UUID | None = None
    ar_account_id: uuid.UUID | None = None
    revenue_account_id: uuid.UUID | None = None


@router.post("/quotations", status_code=status.HTTP_201_CREATED)
async def create_quotation(
    payload: SalesQuotationCreate,
    db: AsyncSession = Depends(get_db),
    tenant_and_user: tuple[uuid.UUID, uuid.UUID] = Depends(get_current_tenant_and_user),
) -> dict[str, Any]:
    tenant_id, _ = tenant_and_user
    await set_session_tenant(db, tenant_id)
    try:
        items_dict = [item.model_dump() for item in payload.items]
        quotation = await SalesService.create_quotation(
            db=db,
            tenant_id=tenant_id,
            customer_name=payload.customer_name,
            cnpj=payload.cnpj,
            items=items_dict,
        )
        await db.commit()
        return {
            "id": quotation.id,
            "customer_name": quotation.customer_name,
            "cnpj": quotation.cnpj,
            "status": quotation.status,
            "total_amount": quotation.total_amount,
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from e


@router.post("/orders", status_code=status.HTTP_201_CREATED)
async def create_sales_order(
    payload: SalesOrderCreate,
    db: AsyncSession = Depends(get_db),
    tenant_and_user: tuple[uuid.UUID, uuid.UUID] = Depends(get_current_tenant_and_user),
) -> dict[str, Any]:
    tenant_id, _ = tenant_and_user
    await set_session_tenant(db, tenant_id)
    try:
        items_dict = [item.model_dump() for item in payload.items]
        so = await SalesService.create_sales_order(
            db=db,
            tenant_id=tenant_id,
            customer_name=payload.customer_name,
            cnpj=payload.cnpj,
            items=items_dict,
        )
        await db.commit()
        return {
            "id": so.id,
            "customer_name": so.customer_name,
            "cnpj": so.cnpj,
            "status": so.status,
            "total_amount": so.total_amount,
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from e


@router.post("/orders/{sales_order_id}/approve")
async def approve_sales_order(
    sales_order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_and_user: tuple[uuid.UUID, uuid.UUID] = Depends(get_current_tenant_and_user),
) -> dict[str, Any]:
    tenant_id, _ = tenant_and_user
    await set_session_tenant(db, tenant_id)
    try:
        so = await SalesService.approve_sales_order(db, tenant_id, sales_order_id)
        await db.commit()
        return {"id": so.id, "customer_name": so.customer_name, "status": so.status}
    except SalesOrderNotFoundException as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from e


@router.post("/orders/{sales_order_id}/dispatch", status_code=status.HTTP_201_CREATED)
async def dispatch_sales_order_items(
    sales_order_id: uuid.UUID,
    payload: DispatchSOItemsRequest,
    db: AsyncSession = Depends(get_db),
    tenant_and_user: tuple[uuid.UUID, uuid.UUID] = Depends(get_current_tenant_and_user),
) -> dict[str, Any]:
    tenant_id, _ = tenant_and_user
    await set_session_tenant(db, tenant_id)
    try:
        invoice = await SalesService.dispatch_sales_order_items(
            db=db,
            tenant_id=tenant_id,
            sales_order_id=sales_order_id,
            items_dispatched=payload.items_dispatched,
            invoice_number=payload.invoice_number,
            organization_id=payload.organization_id,
            legal_entity_id=payload.legal_entity_id,
            journal_id=payload.journal_id,
            cmv_account_id=payload.cmv_account_id,
            stock_account_id=payload.stock_account_id,
            ar_account_id=payload.ar_account_id,
            revenue_account_id=payload.revenue_account_id,
        )
        await db.commit()
        return {
            "id": invoice.id,
            "customer_name": invoice.customer_name,
            "number": invoice.number,
            "amount": invoice.amount,
            "status": invoice.status,
        }
    except SalesOrderNotFoundException as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except SalesException as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from e

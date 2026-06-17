import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_tenant_and_user
from app.services.reporting_service import ReportingService

router = APIRouter(prefix="/api/v1/reporting", tags=["Reporting"])


@router.get("/trial-balance")
async def get_trial_balance(
    start_date: date = Query(..., description="Start date of the report"),
    end_date: date = Query(..., description="End date of the report"),
    db: AsyncSession = Depends(get_db),
    tenant_and_user: tuple[uuid.UUID, uuid.UUID] = Depends(get_current_tenant_and_user),
):
    tenant_id, _ = tenant_and_user
    if end_date < start_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end_date cannot be before start_date",
        )
    try:
        return await ReportingService.get_trial_balance(
            db, tenant_id, start_date, end_date
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.get("/income-statement")
async def get_income_statement(
    start_date: date = Query(..., description="Start date of the report"),
    end_date: date = Query(..., description="End date of the report"),
    db: AsyncSession = Depends(get_db),
    tenant_and_user: tuple[uuid.UUID, uuid.UUID] = Depends(get_current_tenant_and_user),
):
    tenant_id, _ = tenant_and_user
    if end_date < start_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end_date cannot be before start_date",
        )
    try:
        return await ReportingService.get_income_statement(
            db, tenant_id, start_date, end_date
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.get("/ageing")
async def get_ageing(
    ageing_type: str = Query(..., description="Ageing type: AP or AR"),
    reference_date: date = Query(
        ..., description="Reference date for calculating overdue days"
    ),
    db: AsyncSession = Depends(get_db),
    tenant_and_user: tuple[uuid.UUID, uuid.UUID] = Depends(get_current_tenant_and_user),
):
    tenant_id, _ = tenant_and_user
    ageing_type_upper = ageing_type.upper()
    if ageing_type_upper not in ["AP", "AR"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ageing_type must be either 'AP' or 'AR'",
        )
    try:
        return await ReportingService.get_ageing_report(
            db, tenant_id, ageing_type_upper, reference_date
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )

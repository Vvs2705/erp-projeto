import re
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, set_session_tenant
from app.core.security import get_current_tenant_and_user
from app.services.finance_service import (
    AccountNotFoundException,
    BillNotFoundException,
    DoubleEntryImbalanceException,
    FinanceException,
    FinanceService,
    FiscalPeriodLockedException,
    FiscalPeriodNotFoundException,
    InvalidAmountException,
    InvoiceNotFoundException,
    JournalNotFoundException,
    OverpaymentException,
)
from app.services.reconciliation_service import (
    ReconciliationException,
    ReconciliationService,
)

router = APIRouter(prefix="/api/v1/finance", tags=["Finance"])

# --- Pydantic DTOs ---


class JournalLineCreate(BaseModel):
    account_id: uuid.UUID
    amount: Decimal = Field(..., gt=0, decimal_places=4)
    direction: str = Field(..., pattern="^(DEBIT|CREDIT)$")
    description: str | None = None


class JournalEntryCreate(BaseModel):
    entry_date: date
    journal_id: uuid.UUID
    description: str
    lines: list[JournalLineCreate] = Field(..., min_length=2)


class BillCreate(BaseModel):
    legal_entity_id: uuid.UUID
    provider_name: str
    cnpj: str = Field(..., description="14 character alphanumeric/numeric CNPJ")
    number: str
    amount: Decimal = Field(..., gt=0, decimal_places=4)
    issue_date: date
    due_date: date
    journal_id: uuid.UUID
    expense_account_id: uuid.UUID
    ap_account_id: uuid.UUID

    @field_validator("cnpj")
    @classmethod
    def validate_cnpj(cls, v: str) -> str:
        if not re.match(r"^[A-Z0-9]{14}$", v):
            raise ValueError(
                "CNPJ must be exactly 14 alphanumeric uppercase characters."
            )
        return v


class BillPaymentCreate(BaseModel):
    amount: Decimal = Field(..., gt=0, decimal_places=4)
    payment_date: date
    payment_method: str
    bank_account_info: str | None = None
    journal_id: uuid.UUID
    bank_account_id: uuid.UUID
    ap_account_id: uuid.UUID


class InvoiceCreate(BaseModel):
    legal_entity_id: uuid.UUID
    customer_name: str
    cnpj: str = Field(..., description="14 character alphanumeric/numeric CNPJ")
    number: str
    amount: Decimal = Field(..., gt=0, decimal_places=4)
    issue_date: date
    due_date: date
    journal_id: uuid.UUID
    revenue_account_id: uuid.UUID
    ar_account_id: uuid.UUID

    @field_validator("cnpj")
    @classmethod
    def validate_cnpj(cls, v: str) -> str:
        if not re.match(r"^[A-Z0-9]{14}$", v):
            raise ValueError(
                "CNPJ must be exactly 14 alphanumeric uppercase characters."
            )
        return v


class InvoicePaymentCreate(BaseModel):
    amount: Decimal = Field(..., gt=0, decimal_places=4)
    payment_date: date
    payment_method: str
    bank_account_info: str | None = None
    journal_id: uuid.UUID
    bank_account_id: uuid.UUID
    ar_account_id: uuid.UUID


class BankReconcileRequest(BaseModel):
    journal_entry_id: uuid.UUID
    statement_date: date
    statement_amount: Decimal = Field(..., gt=0, decimal_places=4)


class ConfirmMatchRequest(BaseModel):
    bank_transaction_id: uuid.UUID
    kind: str = Field(..., pattern="^(invoice_payment|bill_payment)$")
    payment_id: uuid.UUID


# --- Endpoints ---


@router.post("/ledger/journal-entries", status_code=status.HTTP_201_CREATED)
async def create_journal_entry(
    payload: JournalEntryCreate,
    db: AsyncSession = Depends(get_db),
    tenant_and_user: tuple[uuid.UUID, uuid.UUID] = Depends(get_current_tenant_and_user),
) -> dict[str, Any]:
    tenant_id, _ = tenant_and_user
    await set_session_tenant(db, tenant_id)
    try:
        lines_dict = [line.model_dump() for line in payload.lines]
        entry = await FinanceService.create_journal_entry(
            db=db,
            tenant_id=tenant_id,
            entry_date=payload.entry_date,
            journal_id=payload.journal_id,
            description=payload.description,
            lines=lines_dict,
        )
        await db.commit()
        return {
            "id": entry.id,
            "status": entry.status,
            "description": entry.description,
            "entry_date": entry.entry_date,
        }
    except (
        FiscalPeriodNotFoundException,
        FiscalPeriodLockedException,
        DoubleEntryImbalanceException,
        InvalidAmountException,
        AccountNotFoundException,
        JournalNotFoundException,
    ) as e:
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


@router.post("/ledger/journal-entries/{entry_id}/post")
async def post_journal_entry(
    entry_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_and_user: tuple[uuid.UUID, uuid.UUID] = Depends(get_current_tenant_and_user),
) -> dict[str, Any]:
    tenant_id, _ = tenant_and_user
    await set_session_tenant(db, tenant_id)
    try:
        entry = await FinanceService.post_journal_entry(db, tenant_id, entry_id)
        await db.commit()
        return {"id": entry.id, "status": entry.status}
    except (FiscalPeriodNotFoundException, FiscalPeriodLockedException) as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e
    except FinanceException as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from e


@router.post("/ledger/fiscal-periods/{period_id}/close")
async def close_fiscal_period(
    period_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_and_user: tuple[uuid.UUID, uuid.UUID] = Depends(get_current_tenant_and_user),
) -> dict[str, Any]:
    tenant_id, _ = tenant_and_user
    await set_session_tenant(db, tenant_id)
    try:
        period = await FinanceService.close_fiscal_period(db, tenant_id, period_id)
        await db.commit()
        return {"id": period.id, "name": period.name, "status": period.status}
    except FiscalPeriodNotFoundException as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from e


@router.post("/ap/bills", status_code=status.HTTP_201_CREATED)
async def create_bill(
    payload: BillCreate,
    db: AsyncSession = Depends(get_db),
    tenant_and_user: tuple[uuid.UUID, uuid.UUID] = Depends(get_current_tenant_and_user),
) -> dict[str, Any]:
    tenant_id, _ = tenant_and_user
    await set_session_tenant(db, tenant_id)
    try:
        bill = await FinanceService.create_bill(
            db=db,
            tenant_id=tenant_id,
            legal_entity_id=payload.legal_entity_id,
            provider_name=payload.provider_name,
            cnpj=payload.cnpj,
            number=payload.number,
            amount=payload.amount,
            issue_date=payload.issue_date,
            due_date=payload.due_date,
            journal_id=payload.journal_id,
            expense_account_id=payload.expense_account_id,
            ap_account_id=payload.ap_account_id,
        )
        await db.commit()
        return {
            "id": bill.id,
            "provider_name": bill.provider_name,
            "number": bill.number,
            "amount": bill.amount,
            "status": bill.status,
        }
    except (
        FiscalPeriodNotFoundException,
        FiscalPeriodLockedException,
        DoubleEntryImbalanceException,
        InvalidAmountException,
        AccountNotFoundException,
        JournalNotFoundException,
    ) as e:
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


@router.post("/ap/bills/{bill_id}/payments", status_code=status.HTTP_201_CREATED)
async def pay_bill(
    bill_id: uuid.UUID,
    payload: BillPaymentCreate,
    db: AsyncSession = Depends(get_db),
    tenant_and_user: tuple[uuid.UUID, uuid.UUID] = Depends(get_current_tenant_and_user),
) -> dict[str, Any]:
    tenant_id, _ = tenant_and_user
    await set_session_tenant(db, tenant_id)
    try:
        payment = await FinanceService.pay_bill(
            db=db,
            tenant_id=tenant_id,
            bill_id=bill_id,
            amount=payload.amount,
            payment_date=payload.payment_date,
            payment_method=payload.payment_method,
            bank_account_info=payload.bank_account_info,
            journal_id=payload.journal_id,
            bank_account_id=payload.bank_account_id,
            ap_account_id=payload.ap_account_id,
        )
        await db.commit()
        return {
            "id": payment.id,
            "bill_id": payment.bill_id,
            "amount": payment.amount,
            "payment_date": payment.payment_date,
            "journal_entry_id": payment.journal_entry_id,
        }
    except BillNotFoundException as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except (
        FiscalPeriodNotFoundException,
        FiscalPeriodLockedException,
        DoubleEntryImbalanceException,
        InvalidAmountException,
        AccountNotFoundException,
        JournalNotFoundException,
        OverpaymentException,
    ) as e:
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


@router.post("/ar/invoices", status_code=status.HTTP_201_CREATED)
async def create_invoice(
    payload: InvoiceCreate,
    db: AsyncSession = Depends(get_db),
    tenant_and_user: tuple[uuid.UUID, uuid.UUID] = Depends(get_current_tenant_and_user),
) -> dict[str, Any]:
    tenant_id, _ = tenant_and_user
    await set_session_tenant(db, tenant_id)
    try:
        invoice = await FinanceService.create_invoice(
            db=db,
            tenant_id=tenant_id,
            legal_entity_id=payload.legal_entity_id,
            customer_name=payload.customer_name,
            cnpj=payload.cnpj,
            number=payload.number,
            amount=payload.amount,
            issue_date=payload.issue_date,
            due_date=payload.due_date,
            journal_id=payload.journal_id,
            revenue_account_id=payload.revenue_account_id,
            ar_account_id=payload.ar_account_id,
        )
        await db.commit()
        return {
            "id": invoice.id,
            "customer_name": invoice.customer_name,
            "number": invoice.number,
            "amount": invoice.amount,
            "status": invoice.status,
        }
    except (
        FiscalPeriodNotFoundException,
        FiscalPeriodLockedException,
        DoubleEntryImbalanceException,
        InvalidAmountException,
        AccountNotFoundException,
        JournalNotFoundException,
    ) as e:
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


@router.post("/ar/invoices/{invoice_id}/payments", status_code=status.HTTP_201_CREATED)
async def pay_invoice(
    invoice_id: uuid.UUID,
    payload: InvoicePaymentCreate,
    db: AsyncSession = Depends(get_db),
    tenant_and_user: tuple[uuid.UUID, uuid.UUID] = Depends(get_current_tenant_and_user),
) -> dict[str, Any]:
    tenant_id, _ = tenant_and_user
    await set_session_tenant(db, tenant_id)
    try:
        payment = await FinanceService.pay_invoice(
            db=db,
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            amount=payload.amount,
            payment_date=payload.payment_date,
            payment_method=payload.payment_method,
            bank_account_info=payload.bank_account_info,
            journal_id=payload.journal_id,
            bank_account_id=payload.bank_account_id,
            ar_account_id=payload.ar_account_id,
        )
        await db.commit()
        return {
            "id": payment.id,
            "invoice_id": payment.invoice_id,
            "amount": payment.amount,
            "payment_date": payment.payment_date,
            "journal_entry_id": payment.journal_entry_id,
        }
    except InvoiceNotFoundException as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except (
        FiscalPeriodNotFoundException,
        FiscalPeriodLockedException,
        DoubleEntryImbalanceException,
        InvalidAmountException,
        AccountNotFoundException,
        JournalNotFoundException,
        OverpaymentException,
    ) as e:
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


@router.post("/reconciliation")
async def reconcile_bank_transaction(
    payload: BankReconcileRequest,
    db: AsyncSession = Depends(get_db),
    tenant_and_user: tuple[uuid.UUID, uuid.UUID] = Depends(get_current_tenant_and_user),
) -> dict[str, Any]:
    tenant_id, _ = tenant_and_user
    await set_session_tenant(db, tenant_id)
    matched = await FinanceService.reconcile_bank_transaction(
        db=db,
        tenant_id=tenant_id,
        journal_entry_id=payload.journal_entry_id,
        statement_date=payload.statement_date,
        statement_amount=payload.statement_amount,
    )
    if not matched:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Bank transaction reconciliation failed. No matching journal "
                "entry found, or date/amount mismatch."
            ),
        )
    return {"reconciled": True, "journal_entry_id": payload.journal_entry_id}


@router.get("/reconciliation/suggestions")
async def reconciliation_suggestions(
    start_date: date = Query(..., description="Início do período do extrato"),
    end_date: date = Query(..., description="Fim do período do extrato"),
    date_tolerance_days: int = Query(
        3, ge=0, description="Janela de dias para casar a data do pagamento"
    ),
    db: AsyncSession = Depends(get_db),
    tenant_and_user: tuple[uuid.UUID, uuid.UUID] = Depends(get_current_tenant_and_user),
) -> dict[str, Any]:
    tenant_id, _ = tenant_and_user
    if end_date < start_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end_date cannot be before start_date",
        )
    await set_session_tenant(db, tenant_id)
    suggestions = await ReconciliationService.suggest_matches(
        db, tenant_id, start_date, end_date, date_tolerance_days
    )
    return {"suggestions": suggestions}


@router.post("/reconciliation/confirm")
async def reconciliation_confirm(
    payload: ConfirmMatchRequest,
    db: AsyncSession = Depends(get_db),
    tenant_and_user: tuple[uuid.UUID, uuid.UUID] = Depends(get_current_tenant_and_user),
) -> dict[str, Any]:
    tenant_id, _ = tenant_and_user
    await set_session_tenant(db, tenant_id)
    try:
        bt = await ReconciliationService.confirm_match(
            db,
            tenant_id,
            payload.bank_transaction_id,
            payload.kind,
            payload.payment_id,
        )
    except ReconciliationException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e
    return {
        "reconciled": True,
        "bank_transaction_id": bt.id,
        "matched_kind": bt.matched_kind,
        "matched_payment_id": bt.matched_payment_id,
    }


@router.post("/reconciliation/auto")
async def reconciliation_auto(
    start_date: date = Query(..., description="Início do período do extrato"),
    end_date: date = Query(..., description="Fim do período do extrato"),
    date_tolerance_days: int = Query(
        3, ge=0, description="Janela de dias para casar a data do pagamento"
    ),
    db: AsyncSession = Depends(get_db),
    tenant_and_user: tuple[uuid.UUID, uuid.UUID] = Depends(get_current_tenant_and_user),
) -> dict[str, Any]:
    tenant_id, _ = tenant_and_user
    if end_date < start_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end_date cannot be before start_date",
        )
    await set_session_tenant(db, tenant_id)
    return await ReconciliationService.auto_reconcile(
        db, tenant_id, start_date, end_date, date_tolerance_days
    )

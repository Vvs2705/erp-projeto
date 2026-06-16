import uuid
from datetime import date
from decimal import Decimal
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Header, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, set_session_tenant
from app.services.finance_service import FinanceService
from app.models.finance import Invoice, Bill, Account, Journal
from app.models.tenant import TransactionalOutbox

router = APIRouter(prefix="/api/v1/integrations/banking", tags=["Banking Integrations"])

# --- Pydantic DTOs ---

class PixWebhookPayload(BaseModel):
    event: str = Field(..., description="Event type, e.g. pix.completed")
    txid: str = Field(..., description="Pix transaction ID")
    amount: Decimal = Field(..., gt=0, decimal_places=4)
    payment_date: date
    invoice_id: Optional[uuid.UUID] = None
    tenant_id: Optional[uuid.UUID] = None
    # Optional accounts to bypass automatic lookup
    journal_id: Optional[uuid.UUID] = None
    bank_account_id: Optional[uuid.UUID] = None
    ar_account_id: Optional[uuid.UUID] = None

class BoletoWebhookPayload(BaseModel):
    event: str = Field(..., description="Event type, e.g. boleto.paid")
    our_number: str = Field(..., description="Boleto our number (nosso numero)")
    amount: Decimal = Field(..., gt=0, decimal_places=4)
    payment_date: date
    bill_id: Optional[uuid.UUID] = None
    invoice_id: Optional[uuid.UUID] = None
    tenant_id: Optional[uuid.UUID] = None
    # Optional accounts to bypass automatic lookup
    journal_id: Optional[uuid.UUID] = None
    bank_account_id: Optional[uuid.UUID] = None
    ap_account_id: Optional[uuid.UUID] = None
    ar_account_id: Optional[uuid.UUID] = None


# --- Helpers ---

async def verify_signature_or_token(request: Request, x_webhook_token: Optional[str] = Header(None)):
    """
    Validates webhook authenticity via secret token or signature.
    """
    token = x_webhook_token or request.headers.get("Authorization")
    signature = request.headers.get("X-Signature")
    
    # We accept "secret_webhook_token" (or Bearer secret_webhook_token) or a simulated signature
    if token and ("secret_webhook_token" in token):
        return True
    if signature and len(signature) > 10:  # Mock signature check
        return True
        
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing webhook authorization token or signature"
    )

async def resolve_tenant_id(
    payload_tenant_id: Optional[uuid.UUID],
    x_tenant_id: Optional[str] = Header(None)
) -> uuid.UUID:
    """
    Resolves tenant ID from request header or payload.
    """
    tenant_str = x_tenant_id
    if tenant_str:
        try:
            return uuid.UUID(tenant_str)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid X-Tenant-ID header format. Must be a valid UUID."
            )
            
    if payload_tenant_id:
        return payload_tenant_id
        
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Tenant ID is required (via X-Tenant-ID header or payload)"
    )

async def get_accounts_for_settlement(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    is_invoice: bool
):
    """
    Auto-discovers Journal and Account records for settlement if not explicitly provided.
    """
    # 1. Accounts
    stmt = select(Account).where(Account.tenant_id == tenant_id)
    res = await db.execute(stmt)
    accounts = res.scalars().all()
    
    bank_account = None
    ar_ap_account = None
    
    # Find bank account (Asset)
    for acc in accounts:
        if acc.type == "asset" and ("cash" in acc.name.lower() or "bank" in acc.name.lower() or acc.code == "1.1.01.001"):
            bank_account = acc
            break
    if not bank_account:
        # Fallback to first asset account
        for acc in accounts:
            if acc.type == "asset":
                bank_account = acc
                break
    if not bank_account and accounts:
        bank_account = accounts[0]
        
    # Find settlement account (AR Asset for Invoices, AP Liability for Bills)
    if is_invoice:
        for acc in accounts:
            if acc.type == "asset" and acc != bank_account and ("receivable" in acc.name.lower() or "client" in acc.name.lower() or acc.code.startswith("1.1.02")):
                ar_ap_account = acc
                break
        if not ar_ap_account:
            # Fallback to another asset
            for acc in accounts:
                if acc.type == "asset" and acc != bank_account:
                    ar_ap_account = acc
                    break
    else:
        for acc in accounts:
            if acc.type == "liability" and ("payable" in acc.name.lower() or "provider" in acc.name.lower() or acc.code.startswith("2.1.01")):
                ar_ap_account = acc
                break
        if not ar_ap_account:
            # Fallback to first liability
            for acc in accounts:
                if acc.type == "liability":
                    ar_ap_account = acc
                    break
                    
    if not ar_ap_account and accounts:
        ar_ap_account = accounts[-1]
        
    # 2. Journal
    journal_stmt = select(Journal).where(Journal.tenant_id == tenant_id)
    journal_res = await db.execute(journal_stmt)
    journals = journal_res.scalars().all()
    journal = None
    for j in journals:
        if j.code == "CASH" or "cash" in j.name.lower():
            journal = j
            break
    if not journal and journals:
        journal = journals[0]
        
    return journal, bank_account, ar_ap_account


# --- Endpoints ---

@router.post("/webhook/pix", status_code=status.HTTP_200_OK)
async def pix_webhook(
    payload: PixWebhookPayload,
    db: AsyncSession = Depends(get_db),
    authenticated: bool = Depends(verify_signature_or_token),
    x_tenant_id: Optional[str] = Header(None)
):
    """
    Webhook receiver for Pix payment completion notices.
    """
    tenant_id = await resolve_tenant_id(payload.tenant_id, x_tenant_id)
    await set_session_tenant(db, tenant_id)
    
    # 1. Record incoming event in Outbox/Inbox table
    inbox_event = TransactionalOutbox(
        tenant_id=tenant_id,
        event_type="pix_payment_received",
        payload=payload.model_dump(exclude_none=True),
        status="completed"
    )
    db.add(inbox_event)
    await db.flush()
    
    # 2. Find corresponding Invoice
    invoice = None
    if payload.invoice_id:
        invoice_stmt = select(Invoice).where(Invoice.tenant_id == tenant_id, Invoice.id == payload.invoice_id)
        invoice_res = await db.execute(invoice_stmt)
        invoice = invoice_res.scalar_one_or_none()
        
    if not invoice:
        # Attempt lookup by number (matching payload txid or prefix of txid)
        invoice_stmt = select(Invoice).where(Invoice.tenant_id == tenant_id, Invoice.number == payload.txid)
        invoice_res = await db.execute(invoice_stmt)
        invoice = invoice_res.scalar_one_or_none()
        
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invoice not found for ID/txid: {payload.invoice_id or payload.txid}"
        )
        
    # 3. Resolve accounts and journal
    journal_id = payload.journal_id
    bank_account_id = payload.bank_account_id
    ar_account_id = payload.ar_account_id
    
    if not (journal_id and bank_account_id and ar_account_id):
        disc_journal, disc_bank, disc_ar = await get_accounts_for_settlement(db, tenant_id, is_invoice=True)
        if not journal_id and disc_journal:
            journal_id = disc_journal.id
        if not bank_account_id and disc_bank:
            bank_account_id = disc_bank.id
        if not ar_account_id and disc_ar:
            ar_account_id = disc_ar.id
            
    if not (journal_id and bank_account_id and ar_account_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not automatically resolve accounts and journal for settlement. Please provide them in the request."
        )
        
    # 4. Perform payment liquidation using FinanceService
    try:
        payment = await FinanceService.pay_invoice(
            db=db,
            tenant_id=tenant_id,
            invoice_id=invoice.id,
            amount=payload.amount,
            payment_date=payload.payment_date,
            payment_method="PIX",
            bank_account_info=f"Pix txid: {payload.txid}",
            journal_id=journal_id,
            bank_account_id=bank_account_id,
            ar_account_id=ar_account_id
        )
        await db.commit()
        return {
            "status": "processed",
            "invoice_status": invoice.status,
            "payment_id": payment.id,
            "journal_entry_id": payment.journal_entry_id
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Liquidation failed: {str(e)}"
        )


@router.post("/webhook/boleto", status_code=status.HTTP_200_OK)
async def boleto_webhook(
    payload: BoletoWebhookPayload,
    db: AsyncSession = Depends(get_db),
    authenticated: bool = Depends(verify_signature_or_token),
    x_tenant_id: Optional[str] = Header(None)
):
    """
    Webhook receiver for Boleto payment completion notices.
    """
    tenant_id = await resolve_tenant_id(payload.tenant_id, x_tenant_id)
    await set_session_tenant(db, tenant_id)
    
    # 1. Record incoming event in Outbox/Inbox table
    inbox_event = TransactionalOutbox(
        tenant_id=tenant_id,
        event_type="boleto_payment_received",
        payload=payload.model_dump(exclude_none=True),
        status="completed"
    )
    db.add(inbox_event)
    await db.flush()
    
    # 2. Find corresponding Invoice or Bill
    invoice = None
    bill = None
    
    if payload.invoice_id:
        invoice_stmt = select(Invoice).where(Invoice.tenant_id == tenant_id, Invoice.id == payload.invoice_id)
        invoice_res = await db.execute(invoice_stmt)
        invoice = invoice_res.scalar_one_or_none()
    elif payload.bill_id:
        bill_stmt = select(Bill).where(Bill.tenant_id == tenant_id, Bill.id == payload.bill_id)
        bill_res = await db.execute(bill_stmt)
        bill = bill_res.scalar_one_or_none()
        
    if not invoice and not bill:
        # Fallback to look up invoice by number
        invoice_stmt = select(Invoice).where(Invoice.tenant_id == tenant_id, Invoice.number == payload.our_number)
        invoice_res = await db.execute(invoice_stmt)
        invoice = invoice_res.scalar_one_or_none()
        
    if not invoice and not bill:
        # Fallback to look up bill by number
        bill_stmt = select(Bill).where(Bill.tenant_id == tenant_id, Bill.number == payload.our_number)
        bill_res = await db.execute(bill_stmt)
        bill = bill_res.scalar_one_or_none()
        
    if not invoice and not bill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Settlement target not found for our_number: {payload.our_number}"
        )
        
    # 3. Perform payment liquidation using FinanceService
    try:
        if invoice:
            journal_id = payload.journal_id
            bank_account_id = payload.bank_account_id
            ar_account_id = payload.ar_account_id
            
            if not (journal_id and bank_account_id and ar_account_id):
                disc_journal, disc_bank, disc_ar = await get_accounts_for_settlement(db, tenant_id, is_invoice=True)
                if not journal_id and disc_journal:
                    journal_id = disc_journal.id
                if not bank_account_id and disc_bank:
                    bank_account_id = disc_bank.id
                if not ar_account_id and disc_ar:
                    ar_account_id = disc_ar.id
                    
            if not (journal_id and bank_account_id and ar_account_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Could not automatically resolve accounts and journal for Invoice settlement."
                )
                
            payment = await FinanceService.pay_invoice(
                db=db,
                tenant_id=tenant_id,
                invoice_id=invoice.id,
                amount=payload.amount,
                payment_date=payload.payment_date,
                payment_method="BOLETO",
                bank_account_info=f"Boleto our_number: {payload.our_number}",
                journal_id=journal_id,
                bank_account_id=bank_account_id,
                ar_account_id=ar_account_id
            )
            await db.commit()
            return {
                "status": "processed",
                "invoice_status": invoice.status,
                "payment_id": payment.id,
                "journal_entry_id": payment.journal_entry_id
            }
        else: # Bill payment
            journal_id = payload.journal_id
            bank_account_id = payload.bank_account_id
            ap_account_id = payload.ap_account_id
            
            if not (journal_id and bank_account_id and ap_account_id):
                disc_journal, disc_bank, disc_ap = await get_accounts_for_settlement(db, tenant_id, is_invoice=False)
                if not journal_id and disc_journal:
                    journal_id = disc_journal.id
                if not bank_account_id and disc_bank:
                    bank_account_id = disc_bank.id
                if not ap_account_id and disc_ap:
                    ap_account_id = disc_ap.id
                    
            if not (journal_id and bank_account_id and ap_account_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Could not automatically resolve accounts and journal for Bill settlement."
                )
                
            payment = await FinanceService.pay_bill(
                db=db,
                tenant_id=tenant_id,
                bill_id=bill.id,
                amount=payload.amount,
                payment_date=payload.payment_date,
                payment_method="BOLETO",
                bank_account_info=f"Boleto our_number: {payload.our_number}",
                journal_id=journal_id,
                bank_account_id=bank_account_id,
                ap_account_id=ap_account_id
            )
            await db.commit()
            return {
                "status": "processed",
                "bill_status": bill.status,
                "payment_id": payment.id,
                "journal_entry_id": payment.journal_entry_id
            }
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Liquidation failed: {str(e)}"
        )

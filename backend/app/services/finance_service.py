import uuid
from datetime import date
from decimal import Decimal
from typing import List, Dict, Any, Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finance import (
    Account, FiscalPeriod, Journal, JournalEntry, JournalLine,
    Bill, BillPayment, Invoice, InvoicePayment
)

# Custom Exceptions
class FinanceException(Exception):
    """Base exception for finance module"""
    pass

class FiscalPeriodNotFoundException(FinanceException):
    pass

class FiscalPeriodLockedException(FinanceException):
    pass

class DoubleEntryImbalanceException(FinanceException):
    pass

class InvalidAmountException(FinanceException):
    pass

class AccountNotFoundException(FinanceException):
    pass

class JournalNotFoundException(FinanceException):
    pass

class BillNotFoundException(FinanceException):
    pass

class InvoiceNotFoundException(FinanceException):
    pass

class OverpaymentException(FinanceException):
    pass


class FinanceService:
    @staticmethod
    async def get_active_fiscal_period(
        db: AsyncSession, tenant_id: uuid.UUID, entry_date: date
    ) -> FiscalPeriod:
        """
        Retrieves the fiscal period matching the entry_date and validates it is open.
        """
        stmt = select(FiscalPeriod).where(
            FiscalPeriod.tenant_id == tenant_id,
            FiscalPeriod.start_date <= entry_date,
            FiscalPeriod.end_date >= entry_date,
        )
        result = await db.execute(stmt)
        period = result.scalar_one_or_none()
        if not period:
            raise FiscalPeriodNotFoundException(
                f"No fiscal period defined for date {entry_date}"
            )
        return period

    @staticmethod
    async def create_journal_entry(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        entry_date: date,
        journal_id: uuid.UUID,
        description: str,
        lines: List[Dict[str, Any]],
        status: str = "draft"
    ) -> JournalEntry:
        """
        Business Rule: Double-entry verification.
        - Fiscal period must exist and be open.
        - Sum(debit) == Sum(credit) and both must be greater than zero.
        """
        # 1. Validate Fiscal Period
        period = await FinanceService.get_active_fiscal_period(db, tenant_id, entry_date)
        if period.status in ("locked", "closed"):
            raise FiscalPeriodLockedException(
                f"Fiscal period {period.name} is {period.status}. Modifications are blocked."
            )

        # 2. Check Journal Existence
        journal_stmt = select(Journal).where(Journal.tenant_id == tenant_id, Journal.id == journal_id)
        journal_res = await db.execute(journal_stmt)
        if not journal_res.scalar_one_or_none():
            raise JournalNotFoundException(f"Journal with ID {journal_id} not found.")

        # 3. Double-entry mathematical check
        debit_sum = Decimal("0.0000")
        credit_sum = Decimal("0.0000")
        
        parsed_lines: List[JournalLine] = []
        for idx, line in enumerate(lines):
            account_id = line["account_id"]
            amount = Decimal(str(line["amount"]))
            direction = line["direction"].upper()
            line_desc = line.get("description")

            if amount <= Decimal("0.0000"):
                raise InvalidAmountException(f"Amount in line {idx} must be greater than zero.")

            # Validate account exists
            acc_stmt = select(Account).where(Account.tenant_id == tenant_id, Account.id == account_id)
            acc_res = await db.execute(acc_stmt)
            if not acc_res.scalar_one_or_none():
                raise AccountNotFoundException(f"Account with ID {account_id} not found.")

            if direction == "DEBIT":
                debit_sum += amount
            elif direction == "CREDIT":
                credit_sum += amount
            else:
                raise ValueError(f"Invalid direction in line {idx}: {direction}. Must be DEBIT or CREDIT.")

            parsed_lines.append(
                JournalLine(
                    tenant_id=tenant_id,
                    account_id=account_id,
                    amount=amount,
                    direction=direction,
                    description=line_desc,
                )
            )

        if abs(debit_sum - credit_sum) >= Decimal("0.0001"):
            raise DoubleEntryImbalanceException(
                f"Imbalanced journal entry. Debits: {debit_sum}, Credits: {credit_sum}."
            )

        if debit_sum <= Decimal("0.0000"):
            raise InvalidAmountException("Journal entry amount must be greater than zero.")

        # 4. Create and persist Journal Entry
        entry = JournalEntry(
            tenant_id=tenant_id,
            entry_date=entry_date,
            journal_id=journal_id,
            description=description,
            status=status,
            lines=parsed_lines,
        )
        db.add(entry)
        await db.flush()
        return entry

    @staticmethod
    async def post_journal_entry(
        db: AsyncSession, tenant_id: uuid.UUID, entry_id: uuid.UUID
    ) -> JournalEntry:
        """
        Posts a draft journal entry. Validates fiscal period before posting.
        """
        stmt = select(JournalEntry).where(
            JournalEntry.tenant_id == tenant_id, JournalEntry.id == entry_id
        )
        result = await db.execute(stmt)
        entry = result.scalar_one_or_none()
        if not entry:
            raise FinanceException(f"Journal entry {entry_id} not found.")

        if entry.status == "posted":
            return entry

        # Verify period is still open
        period = await FinanceService.get_active_fiscal_period(db, tenant_id, entry.entry_date)
        if period.status in ("locked", "closed"):
            raise FiscalPeriodLockedException(
                f"Fiscal period {period.name} is {period.status}. Cannot post entry."
            )

        entry.status = "posted"
        await db.flush()
        return entry

    @staticmethod
    async def close_fiscal_period(
        db: AsyncSession, tenant_id: uuid.UUID, period_id: uuid.UUID
    ) -> FiscalPeriod:
        """
        Locks a fiscal period, preventing modifications to entries within its range.
        """
        stmt = select(FiscalPeriod).where(
            FiscalPeriod.tenant_id == tenant_id, FiscalPeriod.id == period_id
        )
        result = await db.execute(stmt)
        period = result.scalar_one_or_none()
        if not period:
            raise FiscalPeriodNotFoundException(f"Fiscal period {period_id} not found.")

        period.status = "locked"
        await db.flush()
        return period

    @staticmethod
    async def create_bill(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        legal_entity_id: uuid.UUID,
        provider_name: str,
        cnpj: str,
        number: str,
        amount: Decimal,
        issue_date: date,
        due_date: date,
        journal_id: uuid.UUID,
        expense_account_id: uuid.UUID,
        ap_account_id: uuid.UUID,
    ) -> Bill:
        """
        Accounts Payable: Creates a Bill and its corresponding ledger provision.
        Provision entry: Debit (Expense Account) and Credit (AP Liability Account).
        """
        # 1. Create the Bill
        bill = Bill(
            tenant_id=tenant_id,
            legal_entity_id=legal_entity_id,
            provider_name=provider_name,
            cnpj=cnpj,
            number=number,
            amount=amount,
            issue_date=issue_date,
            due_date=due_date,
            status="pending",
        )
        db.add(bill)
        await db.flush()

        # 2. Create provision Journal Entry (Partida Dobrada)
        lines = [
            {"account_id": expense_account_id, "amount": amount, "direction": "DEBIT", "description": f"Expense provision for Bill {number}"},
            {"account_id": ap_account_id, "amount": amount, "direction": "CREDIT", "description": f"AP provision for Bill {number}"},
        ]
        
        await FinanceService.create_journal_entry(
            db=db,
            tenant_id=tenant_id,
            entry_date=issue_date,
            journal_id=journal_id,
            description=f"Provision of Bill {number} - {provider_name}",
            lines=lines,
            status="posted"
        )
        
        return bill

    @staticmethod
    async def pay_bill(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        bill_id: uuid.UUID,
        amount: Decimal,
        payment_date: date,
        payment_method: str,
        bank_account_info: Optional[str],
        journal_id: uuid.UUID,
        bank_account_id: uuid.UUID,
        ap_account_id: uuid.UUID,
    ) -> BillPayment:
        """
        Accounts Payable: Pays a Bill (fully or partially) and generates the payment ledger entry.
        Payment Entry: Debit (AP Liability Account) and Credit (Bank/Cash Asset Account).
        """
        # 1. Retrieve the Bill
        bill_stmt = select(Bill).where(Bill.tenant_id == tenant_id, Bill.id == bill_id)
        bill_res = await db.execute(bill_stmt)
        bill = bill_res.scalar_one_or_none()
        if not bill:
            raise BillNotFoundException(f"Bill with ID {bill_id} not found.")

        # Check total payments
        total_paid_stmt = select(func.sum(BillPayment.amount)).where(BillPayment.bill_id == bill_id)
        total_paid_res = await db.execute(total_paid_stmt)
        total_paid = total_paid_res.scalar() or Decimal("0.0000")

        remaining = bill.amount - total_paid
        if amount > remaining:
            raise OverpaymentException(
                f"Payment amount {amount} exceeds remaining bill balance {remaining}."
            )

        # 2. Create the payment Journal Entry (Partida Dobrada)
        lines = [
            {"account_id": ap_account_id, "amount": amount, "direction": "DEBIT", "description": f"AP settlement for Bill {bill.number}"},
            {"account_id": bank_account_id, "amount": amount, "direction": "CREDIT", "description": f"Bank payment for Bill {bill.number}"},
        ]

        payment_entry = await FinanceService.create_journal_entry(
            db=db,
            tenant_id=tenant_id,
            entry_date=payment_date,
            journal_id=journal_id,
            description=f"Payment of Bill {bill.number} - {bill.provider_name}",
            lines=lines,
            status="posted"
        )

        # 3. Save the Payment record
        payment = BillPayment(
            tenant_id=tenant_id,
            bill_id=bill_id,
            amount=amount,
            payment_date=payment_date,
            payment_method=payment_method,
            bank_account_info=bank_account_info,
            journal_entry_id=payment_entry.id,
        )
        db.add(payment)

        # Update Bill Status
        if total_paid + amount >= bill.amount:
            bill.status = "paid"
        else:
            bill.status = "partially_paid"

        await db.flush()
        return payment

    @staticmethod
    async def create_invoice(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        legal_entity_id: uuid.UUID,
        customer_name: str,
        cnpj: str,
        number: str,
        amount: Decimal,
        issue_date: date,
        due_date: date,
        journal_id: uuid.UUID,
        revenue_account_id: uuid.UUID,
        ar_account_id: uuid.UUID,
    ) -> Invoice:
        """
        Accounts Receivable: Creates an Invoice and its corresponding ledger provision.
        Provision entry: Debit (AR Asset Account) and Credit (Revenue Account).
        """
        # 1. Create the Invoice
        invoice = Invoice(
            tenant_id=tenant_id,
            legal_entity_id=legal_entity_id,
            customer_name=customer_name,
            cnpj=cnpj,
            number=number,
            amount=amount,
            issue_date=issue_date,
            due_date=due_date,
            status="pending",
        )
        db.add(invoice)
        await db.flush()

        # 2. Create provision Journal Entry (Partida Dobrada)
        lines = [
            {"account_id": ar_account_id, "amount": amount, "direction": "DEBIT", "description": f"AR provision for Invoice {number}"},
            {"account_id": revenue_account_id, "amount": amount, "direction": "CREDIT", "description": f"Revenue provision for Invoice {number}"},
        ]
        
        await FinanceService.create_journal_entry(
            db=db,
            tenant_id=tenant_id,
            entry_date=issue_date,
            journal_id=journal_id,
            description=f"Provision of Invoice {number} - {customer_name}",
            lines=lines,
            status="posted"
        )
        
        return invoice

    @staticmethod
    async def pay_invoice(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        invoice_id: uuid.UUID,
        amount: Decimal,
        payment_date: date,
        payment_method: str,
        bank_account_info: Optional[str],
        journal_id: uuid.UUID,
        bank_account_id: uuid.UUID,
        ar_account_id: uuid.UUID,
    ) -> InvoicePayment:
        """
        Accounts Receivable: Receives payment for an Invoice (fully or partially) and generates the payment ledger entry.
        Payment Entry: Debit (Bank/Cash Asset Account) and Credit (AR Asset Account).
        """
        # 1. Retrieve the Invoice
        invoice_stmt = select(Invoice).where(Invoice.tenant_id == tenant_id, Invoice.id == invoice_id)
        invoice_res = await db.execute(invoice_stmt)
        invoice = invoice_res.scalar_one_or_none()
        if not invoice:
            raise InvoiceNotFoundException(f"Invoice with ID {invoice_id} not found.")

        # Check total payments
        total_paid_stmt = select(func.sum(InvoicePayment.amount)).where(InvoicePayment.invoice_id == invoice_id)
        total_paid_res = await db.execute(total_paid_stmt)
        total_paid = total_paid_res.scalar() or Decimal("0.0000")

        remaining = invoice.amount - total_paid
        if amount > remaining:
            raise OverpaymentException(
                f"Receipt amount {amount} exceeds remaining invoice balance {remaining}."
            )

        # 2. Create the payment Journal Entry (Partida Dobrada)
        lines = [
            {"account_id": bank_account_id, "amount": amount, "direction": "DEBIT", "description": f"Bank receipt for Invoice {invoice.number}"},
            {"account_id": ar_account_id, "amount": amount, "direction": "CREDIT", "description": f"AR settlement for Invoice {invoice.number}"},
        ]

        payment_entry = await FinanceService.create_journal_entry(
            db=db,
            tenant_id=tenant_id,
            entry_date=payment_date,
            journal_id=journal_id,
            description=f"Receipt for Invoice {invoice.number} - {invoice.customer_name}",
            lines=lines,
            status="posted"
        )

        # 3. Save the Payment record
        payment = InvoicePayment(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            amount=amount,
            payment_date=payment_date,
            payment_method=payment_method,
            bank_account_info=bank_account_info,
            journal_entry_id=payment_entry.id,
        )
        db.add(payment)

        # Update Invoice Status
        if total_paid + amount >= invoice.amount:
            invoice.status = "paid"
        else:
            invoice.status = "partially_paid"

        await db.flush()
        return payment

    @staticmethod
    async def reconcile_bank_transaction(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        journal_entry_id: uuid.UUID,
        statement_date: date,
        statement_amount: Decimal,
    ) -> bool:
        """
        Initial bank reconciliation helper:
        Matches a bank statement line to a JournalEntry in the database.
        Checks if the journal entry is posted, matches the date (within a 3-day window),
        and the absolute sum of DEBIT/CREDIT lines matches the statement amount.
        """
        stmt = select(JournalEntry).where(
            JournalEntry.tenant_id == tenant_id, JournalEntry.id == journal_entry_id
        )
        result = await db.execute(stmt)
        entry = result.scalar_one_or_none()
        if not entry:
            return False

        if entry.status != "posted":
            return False

        # Date window check: within 3 days of statement
        days_diff = abs((entry.entry_date - statement_date).days)
        if days_diff > 3:
            return False

        # Verify sum of transaction matches statement_amount
        # In double-entry, debit sum = credit sum. We match the total transaction value.
        total_value = Decimal("0.0000")
        for line in entry.lines:
            if line.direction == "DEBIT":
                total_value += line.amount

        if abs(total_value - statement_amount) >= Decimal("0.0001"):
            return False

        # Realistically, here we could flag the JournalEntry/lines as 'reconciled' or save a log
        # For this initial phase, we return True if matched and verified.
        return True

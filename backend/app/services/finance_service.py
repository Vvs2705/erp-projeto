import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.finance import (
    Account,
    Bill,
    BillPayment,
    FiscalPeriod,
    Invoice,
    InvoicePayment,
    Journal,
    JournalEntry,
    JournalLine,
    PeriodClosing,
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


class PostedEntryImmutableException(FinanceException):
    pass


class PeriodAlreadyClosedException(FinanceException):
    pass


class PeriodClosingAccountMissingException(FinanceException):
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
        lines: list[dict[str, Any]],
        status: str = "draft",
    ) -> JournalEntry:
        """
        Business Rule: Double-entry verification.
        - Fiscal period must exist and be open.
        - Sum(debit) == Sum(credit) and both must be greater than zero.
        """
        # 1. Validate Fiscal Period
        period = await FinanceService.get_active_fiscal_period(
            db, tenant_id, entry_date
        )
        if period.status in ("locked", "closed"):
            raise FiscalPeriodLockedException(
                f"Fiscal period {period.name} is {period.status}. "
                "Modifications are blocked."
            )

        # 2. Check Journal Existence
        journal_stmt = select(Journal).where(
            Journal.tenant_id == tenant_id, Journal.id == journal_id
        )
        journal_res = await db.execute(journal_stmt)
        if not journal_res.scalar_one_or_none():
            raise JournalNotFoundException(f"Journal with ID {journal_id} not found.")

        # 3. Double-entry mathematical check
        debit_sum = Decimal("0.0000")
        credit_sum = Decimal("0.0000")

        parsed_lines: list[JournalLine] = []
        for idx, line in enumerate(lines):
            account_id = line["account_id"]
            amount = Decimal(str(line["amount"]))
            direction = line["direction"].upper()
            line_desc = line.get("description")

            if amount <= Decimal("0.0000"):
                raise InvalidAmountException(
                    f"Amount in line {idx} must be greater than zero."
                )

            # Validate account exists
            acc_stmt = select(Account).where(
                Account.tenant_id == tenant_id, Account.id == account_id
            )
            acc_res = await db.execute(acc_stmt)
            if not acc_res.scalar_one_or_none():
                raise AccountNotFoundException(
                    f"Account with ID {account_id} not found."
                )

            if direction == "DEBIT":
                debit_sum += amount
            elif direction == "CREDIT":
                credit_sum += amount
            else:
                raise ValueError(
                    f"Invalid direction in line {idx}: {direction}. "
                    "Must be DEBIT or CREDIT."
                )

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
            raise InvalidAmountException(
                "Journal entry amount must be greater than zero."
            )

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
        period = await FinanceService.get_active_fiscal_period(
            db, tenant_id, entry.entry_date
        )
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
            {
                "account_id": expense_account_id,
                "amount": amount,
                "direction": "DEBIT",
                "description": f"Expense provision for Bill {number}",
            },
            {
                "account_id": ap_account_id,
                "amount": amount,
                "direction": "CREDIT",
                "description": f"AP provision for Bill {number}",
            },
        ]

        await FinanceService.create_journal_entry(
            db=db,
            tenant_id=tenant_id,
            entry_date=issue_date,
            journal_id=journal_id,
            description=f"Provision of Bill {number} - {provider_name}",
            lines=lines,
            status="posted",
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
        bank_account_info: str | None,
        journal_id: uuid.UUID,
        bank_account_id: uuid.UUID,
        ap_account_id: uuid.UUID,
    ) -> BillPayment:
        """
        Accounts Payable: Pays a Bill (fully or partially) and generates the
        payment ledger entry.
        Payment Entry: Debit (AP Liability Account) and Credit (Bank/Cash Asset
        Account).
        """
        # 1. Retrieve the Bill
        bill_stmt = select(Bill).where(Bill.tenant_id == tenant_id, Bill.id == bill_id)
        bill_res = await db.execute(bill_stmt)
        bill = bill_res.scalar_one_or_none()
        if not bill:
            raise BillNotFoundException(f"Bill with ID {bill_id} not found.")

        # Check total payments
        total_paid_stmt = select(func.sum(BillPayment.amount)).where(
            BillPayment.bill_id == bill_id
        )
        total_paid_res = await db.execute(total_paid_stmt)
        total_paid = total_paid_res.scalar() or Decimal("0.0000")

        remaining = bill.amount - total_paid
        if amount > remaining:
            raise OverpaymentException(
                f"Payment amount {amount} exceeds remaining bill balance {remaining}."
            )

        # 2. Create the payment Journal Entry (Partida Dobrada)
        lines = [
            {
                "account_id": ap_account_id,
                "amount": amount,
                "direction": "DEBIT",
                "description": f"AP settlement for Bill {bill.number}",
            },
            {
                "account_id": bank_account_id,
                "amount": amount,
                "direction": "CREDIT",
                "description": f"Bank payment for Bill {bill.number}",
            },
        ]

        payment_entry = await FinanceService.create_journal_entry(
            db=db,
            tenant_id=tenant_id,
            entry_date=payment_date,
            journal_id=journal_id,
            description=f"Payment of Bill {bill.number} - {bill.provider_name}",
            lines=lines,
            status="posted",
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
            {
                "account_id": ar_account_id,
                "amount": amount,
                "direction": "DEBIT",
                "description": f"AR provision for Invoice {number}",
            },
            {
                "account_id": revenue_account_id,
                "amount": amount,
                "direction": "CREDIT",
                "description": f"Revenue provision for Invoice {number}",
            },
        ]

        await FinanceService.create_journal_entry(
            db=db,
            tenant_id=tenant_id,
            entry_date=issue_date,
            journal_id=journal_id,
            description=f"Provision of Invoice {number} - {customer_name}",
            lines=lines,
            status="posted",
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
        bank_account_info: str | None,
        journal_id: uuid.UUID,
        bank_account_id: uuid.UUID,
        ar_account_id: uuid.UUID,
    ) -> InvoicePayment:
        """
        Accounts Receivable: Receives payment for an Invoice (fully or
        partially) and generates the payment ledger entry.
        Payment Entry: Debit (Bank/Cash Asset Account) and Credit (AR Asset
        Account).
        """
        # 1. Retrieve the Invoice
        invoice_stmt = select(Invoice).where(
            Invoice.tenant_id == tenant_id, Invoice.id == invoice_id
        )
        invoice_res = await db.execute(invoice_stmt)
        invoice = invoice_res.scalar_one_or_none()
        if not invoice:
            raise InvoiceNotFoundException(f"Invoice with ID {invoice_id} not found.")

        # Check total payments
        total_paid_stmt = select(func.sum(InvoicePayment.amount)).where(
            InvoicePayment.invoice_id == invoice_id
        )
        total_paid_res = await db.execute(total_paid_stmt)
        total_paid = total_paid_res.scalar() or Decimal("0.0000")

        remaining = invoice.amount - total_paid
        if amount > remaining:
            raise OverpaymentException(
                f"Receipt amount {amount} exceeds remaining invoice "
                f"balance {remaining}."
            )

        # 2. Create the payment Journal Entry (Partida Dobrada)
        lines = [
            {
                "account_id": bank_account_id,
                "amount": amount,
                "direction": "DEBIT",
                "description": f"Bank receipt for Invoice {invoice.number}",
            },
            {
                "account_id": ar_account_id,
                "amount": amount,
                "direction": "CREDIT",
                "description": f"AR settlement for Invoice {invoice.number}",
            },
        ]

        payment_entry = await FinanceService.create_journal_entry(
            db=db,
            tenant_id=tenant_id,
            entry_date=payment_date,
            journal_id=journal_id,
            description=(
                f"Receipt for Invoice {invoice.number} - {invoice.customer_name}"
            ),
            lines=lines,
            status="posted",
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
    async def storno_entry(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        original_entry_id: uuid.UUID,
        reversal_date: date,
        journal_id: uuid.UUID,
        reason: str,
    ) -> JournalEntry:
        """Estorno contábil: cria um lançamento de reversão com débitos e
        créditos invertidos.

        O lançamento original permanece imutável; o estorno é um novo lançamento
        postado com sinal oposto e referência ao original na descrição.
        """
        # Carrega o lançamento original com suas linhas
        stmt = (
            select(JournalEntry)
            .options(selectinload(JournalEntry.lines))
            .where(
                JournalEntry.tenant_id == tenant_id,
                JournalEntry.id == original_entry_id,
            )
        )
        result = await db.execute(stmt)
        original = result.scalar_one_or_none()
        if not original:
            raise FinanceException(f"Lançamento {original_entry_id} não encontrado.")

        if original.status == "voided":
            raise FinanceException(f"Lançamento {original_entry_id} já está anulado.")

        # Constrói as linhas invertidas
        reversal_lines: list[dict[str, Any]] = []
        for line in original.lines:
            inverted_direction = "CREDIT" if line.direction == "DEBIT" else "DEBIT"
            reversal_lines.append(
                {
                    "account_id": line.account_id,
                    "amount": line.amount,
                    "direction": inverted_direction,
                    "description": (
                        f"ESTORNO: {line.description or original.description}"
                    ),
                }
            )

        return await FinanceService.create_journal_entry(
            db=db,
            tenant_id=tenant_id,
            entry_date=reversal_date,
            journal_id=journal_id,
            description=f"ESTORNO de {original_entry_id} - {reason}",
            lines=reversal_lines,
            status="posted",
        )

    @staticmethod
    async def close_period_with_result(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        period_id: uuid.UUID,
        closing_journal_id: uuid.UUID,
        retained_earnings_account_id: uuid.UUID,
        closed_by: str,
    ) -> PeriodClosing:
        """Fechamento de período com apuração de resultado.

        1. Calcula o resultado líquido do período (receitas - despesas).
        2. Cria um lançamento de encerramento que zera receitas e despesas,
           transferindo o saldo para a conta de Lucros/Prejuízos Acumulados.
        3. Marca o período como 'closed'.
        4. Registra um PeriodClosing rastreável.

        ``retained_earnings_account_id`` deve ser uma conta de Patrimônio Líquido
        (equity) com natureza 'credit' — tipicamente '3.2.1 - Lucros Acumulados'.
        """
        # 1. Valida o período
        period_stmt = select(FiscalPeriod).where(
            FiscalPeriod.tenant_id == tenant_id, FiscalPeriod.id == period_id
        )
        period_res = await db.execute(period_stmt)
        period = period_res.scalar_one_or_none()
        if not period:
            raise FiscalPeriodNotFoundException(
                f"Período fiscal {period_id} não encontrado."
            )
        if period.status == "closed":
            raise PeriodAlreadyClosedException(
                f"Período {period.name} já está fechado."
            )

        # 2. Valida conta de Lucros Acumulados
        re_acc_stmt = select(Account).where(
            Account.tenant_id == tenant_id, Account.id == retained_earnings_account_id
        )
        re_acc_res = await db.execute(re_acc_stmt)
        re_account = re_acc_res.scalar_one_or_none()
        if not re_account:
            raise PeriodClosingAccountMissingException(
                "Conta de Lucros/Prejuízos Acumulados não encontrada."
            )

        # 3. Calcula saldos de receitas e despesas no período
        result_stmt = (
            select(
                Account.id,
                Account.type,
                Account.nature,
                func.coalesce(
                    func.sum(
                        case(
                            (JournalLine.direction == "DEBIT", JournalLine.amount),
                            else_=0,
                        )
                    ),
                    0,
                ).label("total_debit"),
                func.coalesce(
                    func.sum(
                        case(
                            (JournalLine.direction == "CREDIT", JournalLine.amount),
                            else_=0,
                        )
                    ),
                    0,
                ).label("total_credit"),
            )
            .select_from(Account)
            .outerjoin(
                JournalLine,
                (Account.id == JournalLine.account_id)
                & (JournalLine.tenant_id == tenant_id),
            )
            .outerjoin(
                JournalEntry,
                (JournalLine.journal_entry_id == JournalEntry.id)
                & (JournalEntry.status == "posted")
                & (JournalEntry.tenant_id == tenant_id)
                & (JournalEntry.entry_date >= period.start_date)
                & (JournalEntry.entry_date <= period.end_date),
            )
            .where(
                Account.tenant_id == tenant_id,
                Account.type.in_(["revenue", "expense"]),
            )
            .group_by(Account.id, Account.type, Account.nature)
        )
        result_res = await db.execute(result_stmt)
        result_rows = result_res.all()

        closing_lines: list[dict[str, Any]] = []
        net_result = Decimal("0.0000")

        for row in result_rows:
            debit = Decimal(str(row.total_debit))
            credit = Decimal(str(row.total_credit))

            if row.type == "revenue":
                # Receita: saldo normal credito; balance = credit - debit
                balance = credit - debit
                net_result += balance
                if balance != Decimal("0"):
                    closing_lines.append(
                        {
                            "account_id": row.id,
                            "amount": abs(balance),
                            "direction": "DEBIT",
                            "description": (
                                "Encerramento de receita - apuracao de resultado"
                            ),
                        }
                    )
            else:
                # Despesa: saldo normal debito; balance = debit - credit
                balance = debit - credit
                net_result -= balance
                if balance != Decimal("0"):
                    closing_lines.append(
                        {
                            "account_id": row.id,
                            "amount": abs(balance),
                            "direction": "CREDIT",
                            "description": (
                                "Encerramento de despesa - apuracao de resultado"
                            ),
                        }
                    )

        if not closing_lines:
            # Nenhuma receita ou despesa — cria entry simbólica mínima
            raise FinanceException(
                "Não há lançamentos de receita ou despesa no período para apurar."
            )

        # 4. Contraparte na conta de Lucros/Prejuízos Acumulados
        if net_result >= Decimal("0"):
            # Lucro → crédita Lucros Acumulados
            closing_lines.append(
                {
                    "account_id": retained_earnings_account_id,
                    "amount": net_result,
                    "direction": "CREDIT",
                    "description": (
                        f"Apuração de resultado — lucro do período {period.name}"
                    ),
                }
            )
        else:
            # Prejuízo → debita Lucros Acumulados (reduz PL)
            closing_lines.append(
                {
                    "account_id": retained_earnings_account_id,
                    "amount": abs(net_result),
                    "direction": "DEBIT",
                    "description": (
                        f"Apuração de resultado — prejuízo do período {period.name}"
                    ),
                }
            )

        # 5. Lançamento de encerramento (postado diretamente)
        closing_entry = await FinanceService.create_journal_entry(
            db=db,
            tenant_id=tenant_id,
            entry_date=period.end_date,
            journal_id=closing_journal_id,
            description=f"Apuração de resultado — período {period.name}",
            lines=closing_lines,
            status="posted",
        )

        # 6. Fecha o período
        period.status = "closed"
        await db.flush()

        # 7. Registra o fechamento
        period_closing = PeriodClosing(
            tenant_id=tenant_id,
            fiscal_period_id=period_id,
            closing_entry_id=closing_entry.id,
            net_result=net_result,
            closed_by=closed_by,
        )
        db.add(period_closing)
        await db.flush()
        return period_closing

    @staticmethod
    async def reconcile_bank_transaction(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        journal_entry_id: uuid.UUID,
        statement_date: date,
        statement_amount: Decimal,
        date_tolerance_days: int = 5,
    ) -> bool:
        """Concilia um extrato bancário com um lançamento contábil postado.

        Verifica: (a) lançamento postado, (b) valor bate dentro da tolerância de
        R$ 0,01, (c) data dentro da janela configurável (padrão ±5 dias).
        Sem limite fixo de 3 dias — o chamador controla via ``date_tolerance_days``.
        """
        stmt = (
            select(JournalEntry)
            .options(selectinload(JournalEntry.lines))
            .where(
                JournalEntry.tenant_id == tenant_id, JournalEntry.id == journal_entry_id
            )
        )
        result = await db.execute(stmt)
        entry = result.scalar_one_or_none()
        if not entry:
            return False

        if entry.status != "posted":
            return False

        days_diff = abs((entry.entry_date - statement_date).days)
        if days_diff > date_tolerance_days:
            return False

        total_debit = sum(
            line.amount for line in entry.lines if line.direction == "DEBIT"
        )
        if abs(total_debit - abs(statement_amount)) >= Decimal("0.01"):
            return False

        return True

    @staticmethod
    async def reconcile_statement(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        statement_transactions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Conciliação em lote de um extrato bancário (OFX/JSON do Open Finance).

        Para cada transação do extrato, registra um BankTransaction (por fitid,
        idempotente para re-importacoes) e marca como reconciliado se ja existia.
        Devolve estatísticas e lista de itens novos (nao reconciliados).

        ``statement_transactions`` é o retorno de ``OpenFinanceParser.parse()``:
        lista de dicts com chaves ``id``, ``date``, ``amount``, ``description``.
        """
        from app.models.finance import BankTransaction

        matched = 0
        unmatched: list[dict[str, Any]] = []

        for tx in statement_transactions:
            fitid: str = str(tx.get("id", ""))
            tx_date: date = tx["date"]
            tx_amount: Decimal = Decimal(str(tx["amount"]))
            tx_description: str = str(tx.get("description", ""))

            # Tenta por fitid primeiro (idempotente para re-importações)
            bt_stmt = select(BankTransaction).where(
                BankTransaction.tenant_id == tenant_id,
                BankTransaction.fitid == fitid,
            )
            bt_res = await db.execute(bt_stmt)
            bt = bt_res.scalar_one_or_none()

            if bt is not None:
                if not bt.reconciled:
                    bt.reconciled = True
                    await db.flush()
                matched += 1
                continue

            # Cria BankTransaction para nova linha de extrato
            new_bt = BankTransaction(
                tenant_id=tenant_id,
                fitid=fitid,
                transaction_date=tx_date,
                amount=tx_amount,
                description=tx_description,
                reconciled=False,
            )
            db.add(new_bt)
            await db.flush()
            unmatched.append(
                {
                    "fitid": fitid,
                    "date": tx_date,
                    "amount": tx_amount,
                    "description": tx_description,
                }
            )

        return {
            "total": len(statement_transactions),
            "matched": matched,
            "unmatched_count": len(unmatched),
            "unmatched": unmatched,
        }

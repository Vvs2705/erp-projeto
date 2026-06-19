import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finance import (
    Account,
    Bill,
    BillPayment,
    Invoice,
    InvoicePayment,
    JournalEntry,
    JournalLine,
)


class ReportingService:
    @staticmethod
    async def get_trial_balance(
        db: AsyncSession, tenant_id: uuid.UUID, start_date: date, end_date: date
    ) -> dict[str, Any]:
        """
        Generates the Balancete de Verificação (Trial Balance).
        For each account, calculates the initial balance, period debits, period
        credits, and final balance.
        Ensures the sum of all final debit balances equals the sum of all final
        credit balances.
        """
        stmt = (
            select(
                Account.id,
                Account.code,
                Account.name,
                Account.type,
                func.coalesce(
                    func.sum(
                        case(
                            (
                                JournalEntry.entry_date < start_date,
                                case(
                                    (
                                        JournalLine.direction == "DEBIT",
                                        JournalLine.amount,
                                    ),
                                    else_=0,
                                ),
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("debit_before"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                JournalEntry.entry_date < start_date,
                                case(
                                    (
                                        JournalLine.direction == "CREDIT",
                                        JournalLine.amount,
                                    ),
                                    else_=0,
                                ),
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("credit_before"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                (JournalEntry.entry_date >= start_date)
                                & (JournalEntry.entry_date <= end_date),
                                case(
                                    (
                                        JournalLine.direction == "DEBIT",
                                        JournalLine.amount,
                                    ),
                                    else_=0,
                                ),
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("debit_period"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                (JournalEntry.entry_date >= start_date)
                                & (JournalEntry.entry_date <= end_date),
                                case(
                                    (
                                        JournalLine.direction == "CREDIT",
                                        JournalLine.amount,
                                    ),
                                    else_=0,
                                ),
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("credit_period"),
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
                & (JournalEntry.tenant_id == tenant_id),
            )
            .where(Account.tenant_id == tenant_id)
            .group_by(Account.id, Account.code, Account.name, Account.type)
            .order_by(Account.code)
        )

        result = await db.execute(stmt)
        rows = result.all()

        accounts_report = []
        total_initial_debit = Decimal("0.0000")
        total_initial_credit = Decimal("0.0000")
        total_debit_period = Decimal("0.0000")
        total_credit_period = Decimal("0.0000")
        total_final_debit = Decimal("0.0000")
        total_final_credit = Decimal("0.0000")

        for row in rows:
            debit_before = Decimal(str(row.debit_before))
            credit_before = Decimal(str(row.credit_before))
            debit_period = Decimal(str(row.debit_period))
            credit_period = Decimal(str(row.credit_period))

            # Initial balance
            initial_net = debit_before - credit_before
            if initial_net >= 0:
                initial_balance = initial_net
                initial_direction = "DEBIT"
                total_initial_debit += initial_balance
            else:
                initial_balance = -initial_net
                initial_direction = "CREDIT"
                total_initial_credit += initial_balance

            # Final balance
            final_net = (debit_before + debit_period) - (credit_before + credit_period)
            if final_net >= 0:
                final_balance = final_net
                final_direction = "DEBIT"
                total_final_debit += final_balance
            else:
                final_balance = -final_net
                final_direction = "CREDIT"
                total_final_credit += final_balance

            total_debit_period += debit_period
            total_credit_period += credit_period

            accounts_report.append(
                {
                    "account_id": row.id,
                    "code": row.code,
                    "name": row.name,
                    "type": row.type,
                    "initial_balance": initial_balance,
                    "initial_direction": initial_direction,
                    "debit": debit_period,
                    "credit": credit_period,
                    "final_balance": final_balance,
                    "final_direction": final_direction,
                }
            )

        # Arithmetic validation
        is_balanced = abs(total_final_debit - total_final_credit) < Decimal("0.0001")
        initial_is_balanced = abs(total_initial_debit - total_initial_credit) < Decimal(
            "0.0001"
        )

        if not is_balanced:
            raise ValueError(
                f"Arithmetic imbalance in Trial Balance: total final debits "
                f"({total_final_debit}) does not equal total final credits "
                f"({total_final_credit})."
            )

        return {
            "start_date": start_date,
            "end_date": end_date,
            "totals": {
                "initial_debit": total_initial_debit,
                "initial_credit": total_initial_credit,
                "debit_period": total_debit_period,
                "credit_period": total_credit_period,
                "final_debit": total_final_debit,
                "final_credit": total_final_credit,
                "is_balanced": is_balanced,
                "initial_is_balanced": initial_is_balanced,
            },
            "accounts": accounts_report,
        }

    @staticmethod
    async def get_income_statement(
        db: AsyncSession, tenant_id: uuid.UUID, start_date: date, end_date: date
    ) -> dict[str, Any]:
        """
        Generates the Demonstração do Resultado do Exercício (DRE).
        Groups Revenue and Expense accounts, calculating Gross Revenue, Total
        Expenses, and Net Result.
        """
        stmt = (
            select(
                Account.id,
                Account.code,
                Account.name,
                Account.type,
                func.coalesce(
                    func.sum(
                        case(
                            (
                                (JournalEntry.entry_date >= start_date)
                                & (JournalEntry.entry_date <= end_date),
                                case(
                                    (
                                        JournalLine.direction == "DEBIT",
                                        JournalLine.amount,
                                    ),
                                    else_=0,
                                ),
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("debit_period"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                (JournalEntry.entry_date >= start_date)
                                & (JournalEntry.entry_date <= end_date),
                                case(
                                    (
                                        JournalLine.direction == "CREDIT",
                                        JournalLine.amount,
                                    ),
                                    else_=0,
                                ),
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("credit_period"),
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
                & (JournalEntry.tenant_id == tenant_id),
            )
            .where(
                Account.tenant_id == tenant_id, Account.type.in_(["revenue", "expense"])
            )
            .group_by(Account.id, Account.code, Account.name, Account.type)
            .order_by(Account.code)
        )

        result = await db.execute(stmt)
        rows = result.all()

        revenue_details = []
        expense_details = []
        gross_revenue = Decimal("0.0000")
        total_expenses = Decimal("0.0000")

        for row in rows:
            debit_period = Decimal(str(row.debit_period))
            credit_period = Decimal(str(row.credit_period))

            if row.type == "revenue":
                # Revenues have a normal credit balance
                amount = credit_period - debit_period
                gross_revenue += amount
                revenue_details.append(
                    {
                        "account_id": row.id,
                        "code": row.code,
                        "name": row.name,
                        "amount": amount,
                    }
                )
            elif row.type == "expense":
                # Expenses have a normal debit balance
                amount = debit_period - credit_period
                total_expenses += amount
                expense_details.append(
                    {
                        "account_id": row.id,
                        "code": row.code,
                        "name": row.name,
                        "amount": amount,
                    }
                )

        net_result = gross_revenue - total_expenses

        return {
            "start_date": start_date,
            "end_date": end_date,
            "gross_revenue": gross_revenue,
            "total_expenses": total_expenses,
            "net_result": net_result,
            "revenue_details": revenue_details,
            "expense_details": expense_details,
        }

    @staticmethod
    async def get_ageing_report(
        db: AsyncSession, tenant_id: uuid.UUID, ageing_type: str, reference_date: date
    ) -> dict[str, Any]:
        """
        Calculates the ageing report for Accounts Payable (AP) or Accounts
        Receivable (AR).
        Groups open items (Bill or Invoice with status pending/partially_paid)
        into ageing buckets:
        - A vencer (Not yet due)
        - Atrasado 1-30 dias
        - Atrasado 31-60 dias
        - Atrasado 61-90 dias
        - Atrasado >90 dias
        """
        ageing_type_upper = ageing_type.upper()
        if ageing_type_upper not in ["AP", "AR"]:
            raise ValueError("ageing_type must be either 'AP' or 'AR'")

        if ageing_type_upper == "AP":
            stmt = (
                select(
                    Bill.id,
                    Bill.number,
                    Bill.provider_name.label("partner_name"),
                    Bill.cnpj,
                    Bill.amount,
                    Bill.issue_date,
                    Bill.due_date,
                    func.coalesce(func.sum(BillPayment.amount), 0).label("paid_amount"),
                )
                .select_from(Bill)
                .outerjoin(
                    BillPayment,
                    (Bill.id == BillPayment.bill_id)
                    & (BillPayment.tenant_id == tenant_id),
                )
                .where(
                    Bill.tenant_id == tenant_id,
                    Bill.status.in_(["pending", "partially_paid"]),
                )
                .group_by(
                    Bill.id,
                    Bill.number,
                    Bill.provider_name,
                    Bill.cnpj,
                    Bill.amount,
                    Bill.issue_date,
                    Bill.due_date,
                )
            )
        else:
            stmt = (
                select(
                    Invoice.id,
                    Invoice.number,
                    Invoice.customer_name.label("partner_name"),
                    Invoice.cnpj,
                    Invoice.amount,
                    Invoice.issue_date,
                    Invoice.due_date,
                    func.coalesce(func.sum(InvoicePayment.amount), 0).label(
                        "paid_amount"
                    ),
                )
                .select_from(Invoice)
                .outerjoin(
                    InvoicePayment,
                    (Invoice.id == InvoicePayment.invoice_id)
                    & (InvoicePayment.tenant_id == tenant_id),
                )
                .where(
                    Invoice.tenant_id == tenant_id,
                    Invoice.status.in_(["pending", "partially_paid"]),
                )
                .group_by(
                    Invoice.id,
                    Invoice.number,
                    Invoice.customer_name,
                    Invoice.cnpj,
                    Invoice.amount,
                    Invoice.issue_date,
                    Invoice.due_date,
                )
            )

        result = await db.execute(stmt)
        rows = result.all()

        details = []
        not_yet_due = Decimal("0.0000")
        overdue_1_30 = Decimal("0.0000")
        overdue_31_60 = Decimal("0.0000")
        overdue_61_90 = Decimal("0.0000")
        overdue_above_90 = Decimal("0.0000")
        total_open = Decimal("0.0000")

        for row in rows:
            amount = Decimal(str(row.amount))
            paid_amount = Decimal(str(row.paid_amount))
            open_balance = amount - paid_amount

            # Ignore fully paid rows that might still carry a
            # pending/partially_paid status due to delay
            if open_balance <= Decimal("0.0000"):
                continue

            days_overdue = (reference_date - row.due_date).days

            if days_overdue <= 0:
                bucket = "not_yet_due"
                not_yet_due += open_balance
            elif 1 <= days_overdue <= 30:
                bucket = "1_30"
                overdue_1_30 += open_balance
            elif 31 <= days_overdue <= 60:
                bucket = "31_60"
                overdue_31_60 += open_balance
            elif 61 <= days_overdue <= 90:
                bucket = "61_90"
                overdue_61_90 += open_balance
            else:
                bucket = "above_90"
                overdue_above_90 += open_balance

            total_open += open_balance

            details.append(
                {
                    "id": row.id,
                    "number": row.number,
                    "partner_name": row.partner_name,
                    "cnpj": row.cnpj,
                    "amount": amount,
                    "open_balance": open_balance,
                    "issue_date": row.issue_date,
                    "due_date": row.due_date,
                    "days_overdue": days_overdue,
                    "bucket": bucket,
                }
            )

        return {
            "ageing_type": ageing_type_upper,
            "reference_date": reference_date,
            "summary": {
                "not_yet_due": not_yet_due,
                "overdue_1_30": overdue_1_30,
                "overdue_31_60": overdue_31_60,
                "overdue_61_90": overdue_61_90,
                "overdue_above_90": overdue_above_90,
                "total_open": total_open,
            },
            "details": details,
        }

    @staticmethod
    async def get_balance_sheet(
        db: AsyncSession, tenant_id: uuid.UUID, as_of_date: date
    ) -> dict[str, Any]:
        """Balanço Patrimonial na data especificada.

        Calcula o saldo acumulado de cada conta de Ativo, Passivo e Patrimônio
        Líquido até ``as_of_date`` (inclusive), usando apenas lançamentos postados.
        Valida a equação patrimonial: Ativo = Passivo + PL.
        """
        stmt = (
            select(
                Account.id,
                Account.code,
                Account.name,
                Account.type,
                Account.nature,
                Account.parent_id,
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
                & (JournalEntry.entry_date <= as_of_date),
            )
            .where(
                Account.tenant_id == tenant_id,
                Account.type.in_(["asset", "liability", "equity"]),
            )
            .group_by(
                Account.id,
                Account.code,
                Account.name,
                Account.type,
                Account.nature,
                Account.parent_id,
            )
            .order_by(Account.code)
        )

        result = await db.execute(stmt)
        rows = result.all()

        assets: list[dict[str, Any]] = []
        liabilities: list[dict[str, Any]] = []
        equity: list[dict[str, Any]] = []
        total_assets = Decimal("0.0000")
        total_liabilities = Decimal("0.0000")
        total_equity = Decimal("0.0000")

        for row in rows:
            debit = Decimal(str(row.total_debit))
            credit = Decimal(str(row.total_credit))
            balance = (debit - credit) if row.nature == "debit" else (credit - debit)

            entry: dict[str, Any] = {
                "account_id": row.id,
                "code": row.code,
                "name": row.name,
                "type": row.type,
                "parent_id": row.parent_id,
                "balance": balance,
            }

            if row.type == "asset":
                assets.append(entry)
                total_assets += balance
            elif row.type == "liability":
                liabilities.append(entry)
                total_liabilities += balance
            else:
                equity.append(entry)
                total_equity += balance

        is_balanced = abs(total_assets - (total_liabilities + total_equity)) < Decimal(
            "0.01"
        )

        return {
            "as_of_date": as_of_date,
            "assets": assets,
            "liabilities": liabilities,
            "equity": equity,
            "totals": {
                "total_assets": total_assets,
                "total_liabilities": total_liabilities,
                "total_equity": total_equity,
                "is_balanced": is_balanced,
            },
        }

    @staticmethod
    async def get_ledger(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        account_id: uuid.UUID,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        """Razão analítico de uma conta no período.

        Retorna todos os lançamentos postados de uma conta em ordem cronológica,
        com saldo progressivo (running balance).
        """
        # Busca a conta
        acc_stmt = select(Account).where(
            Account.tenant_id == tenant_id, Account.id == account_id
        )
        acc_result = await db.execute(acc_stmt)
        account = acc_result.scalar_one_or_none()
        if account is None:
            raise ValueError(f"Conta {account_id} não encontrada.")

        # Saldo anterior ao período
        prev_stmt = (
            select(
                func.coalesce(
                    func.sum(
                        case(
                            (JournalLine.direction == "DEBIT", JournalLine.amount),
                            else_=0,
                        )
                    ),
                    0,
                ).label("prev_debit"),
                func.coalesce(
                    func.sum(
                        case(
                            (JournalLine.direction == "CREDIT", JournalLine.amount),
                            else_=0,
                        )
                    ),
                    0,
                ).label("prev_credit"),
            )
            .select_from(JournalLine)
            .join(
                JournalEntry,
                (JournalLine.journal_entry_id == JournalEntry.id)
                & (JournalEntry.status == "posted")
                & (JournalEntry.tenant_id == tenant_id)
                & (JournalEntry.entry_date < start_date),
            )
            .where(
                JournalLine.account_id == account_id,
                JournalLine.tenant_id == tenant_id,
            )
        )
        prev_result = await db.execute(prev_stmt)
        prev_row = prev_result.one()
        prev_debit = Decimal(str(prev_row.prev_debit))
        prev_credit = Decimal(str(prev_row.prev_credit))

        if account.nature == "debit":
            opening_balance = prev_debit - prev_credit
        else:
            opening_balance = prev_credit - prev_debit

        # Lançamentos do período
        period_stmt = (
            select(
                JournalEntry.id.label("entry_id"),
                JournalEntry.entry_date,
                JournalEntry.description.label("entry_description"),
                JournalLine.id.label("line_id"),
                JournalLine.direction,
                JournalLine.amount,
                JournalLine.description.label("line_description"),
            )
            .select_from(JournalLine)
            .join(
                JournalEntry,
                (JournalLine.journal_entry_id == JournalEntry.id)
                & (JournalEntry.status == "posted")
                & (JournalEntry.tenant_id == tenant_id)
                & (JournalEntry.entry_date >= start_date)
                & (JournalEntry.entry_date <= end_date),
            )
            .where(
                JournalLine.account_id == account_id,
                JournalLine.tenant_id == tenant_id,
            )
            .order_by(JournalEntry.entry_date, JournalEntry.id, JournalLine.id)
        )
        period_result = await db.execute(period_stmt)
        period_rows = period_result.all()

        running_balance = opening_balance
        lines: list[dict[str, Any]] = []
        for row in period_rows:
            amount = Decimal(str(row.amount))
            if account.nature == "debit":
                if row.direction == "DEBIT":
                    running_balance += amount
                else:
                    running_balance -= amount
            else:
                if row.direction == "CREDIT":
                    running_balance += amount
                else:
                    running_balance -= amount

            lines.append(
                {
                    "entry_id": row.entry_id,
                    "entry_date": row.entry_date,
                    "description": row.line_description or row.entry_description,
                    "direction": row.direction,
                    "amount": amount,
                    "running_balance": running_balance,
                }
            )

        return {
            "account_id": account_id,
            "account_code": account.code,
            "account_name": account.name,
            "start_date": start_date,
            "end_date": end_date,
            "opening_balance": opening_balance,
            "closing_balance": running_balance,
            "lines": lines,
        }

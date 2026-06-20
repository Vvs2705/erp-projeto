"""Conciliação bancária assistida (determinística, sem IA).

Complementa a conciliação existente (que *valida* um match já conhecido) com a
parte de **descoberta**: para cada linha de extrato (``BankTransaction``) ainda
não conciliada, propõe os pagamentos contabilizados compatíveis por **valor
exato** e **proximidade de data**, registra o vínculo 1:1 escolhido e concilia
automaticamente os casos sem ambiguidade.

Convenção de sinal (OFX): ``amount`` positivo = entrada → casa com
``InvoicePayment`` (recebimento); negativo = saída → casa com ``BillPayment``
(pagamento). A camada de IA (match difuso por descrição) fica para depois; aqui
tudo é exato e auditável.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finance import BankTransaction, BillPayment, InvoicePayment

_ZERO = Decimal("0.0000")
_KINDS = ("invoice_payment", "bill_payment")


class ReconciliationException(Exception):
    """Erro de conciliação bancária (match inválido, valor/sinal incompatível)."""


class ReconciliationService:
    @staticmethod
    async def _consumed_payment_ids(
        db: AsyncSession, tenant_id: uuid.UUID, kind: str
    ) -> set[uuid.UUID]:
        """Ids de pagamentos já vinculados a alguma linha conciliada do tenant."""
        rows = (
            (
                await db.execute(
                    select(BankTransaction.matched_payment_id).where(
                        BankTransaction.tenant_id == tenant_id,
                        BankTransaction.matched_kind == kind,
                        BankTransaction.matched_payment_id.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        return {r for r in rows if r is not None}

    @staticmethod
    async def suggest_matches(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        start_date: date,
        end_date: date,
        date_tolerance_days: int = 3,
    ) -> list[dict[str, Any]]:
        """Propõe candidatos para as linhas de extrato não conciliadas no período.

        Cada candidato casa por valor exato e ``payment_date`` dentro de
        ``±date_tolerance_days`` da data da transação; ordenados por proximidade
        de data. Pagamentos já consumidos por outra conciliação são excluídos.
        """
        if end_date < start_date:
            raise ValueError("end_date não pode ser anterior a start_date")
        if date_tolerance_days < 0:
            raise ValueError("date_tolerance_days não pode ser negativo")

        bts = list(
            (
                await db.execute(
                    select(BankTransaction)
                    .where(
                        BankTransaction.tenant_id == tenant_id,
                        BankTransaction.reconciled.is_(False),
                        BankTransaction.transaction_date >= start_date,
                        BankTransaction.transaction_date <= end_date,
                    )
                    .order_by(BankTransaction.transaction_date)
                )
            )
            .scalars()
            .all()
        )

        consumed_inv = await ReconciliationService._consumed_payment_ids(
            db, tenant_id, "invoice_payment"
        )
        consumed_bill = await ReconciliationService._consumed_payment_ids(
            db, tenant_id, "bill_payment"
        )
        tol = timedelta(days=date_tolerance_days)

        suggestions: list[dict[str, Any]] = []
        for bt in bts:
            candidates: list[dict[str, Any]] = []
            if bt.amount > _ZERO:
                rows = (
                    (
                        await db.execute(
                            select(InvoicePayment).where(
                                InvoicePayment.tenant_id == tenant_id,
                                InvoicePayment.amount == bt.amount,
                                InvoicePayment.payment_date
                                >= bt.transaction_date - tol,
                                InvoicePayment.payment_date
                                <= bt.transaction_date + tol,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for pay in rows:
                    if pay.id in consumed_inv:
                        continue
                    candidates.append(
                        {
                            "kind": "invoice_payment",
                            "payment_id": pay.id,
                            "amount": pay.amount,
                            "payment_date": pay.payment_date,
                            "payment_method": pay.payment_method,
                            "date_distance_days": abs(
                                (pay.payment_date - bt.transaction_date).days
                            ),
                        }
                    )
            elif bt.amount < _ZERO:
                target = -bt.amount
                rows_b = (
                    (
                        await db.execute(
                            select(BillPayment).where(
                                BillPayment.tenant_id == tenant_id,
                                BillPayment.amount == target,
                                BillPayment.payment_date >= bt.transaction_date - tol,
                                BillPayment.payment_date <= bt.transaction_date + tol,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for pay_b in rows_b:
                    if pay_b.id in consumed_bill:
                        continue
                    candidates.append(
                        {
                            "kind": "bill_payment",
                            "payment_id": pay_b.id,
                            "amount": pay_b.amount,
                            "payment_date": pay_b.payment_date,
                            "payment_method": pay_b.payment_method,
                            "date_distance_days": abs(
                                (pay_b.payment_date - bt.transaction_date).days
                            ),
                        }
                    )

            candidates.sort(key=lambda c: c["date_distance_days"])
            suggestions.append(
                {
                    "bank_transaction": {
                        "id": bt.id,
                        "transaction_date": bt.transaction_date,
                        "amount": bt.amount,
                        "description": bt.description,
                    },
                    "candidates": candidates,
                }
            )
        return suggestions

    @staticmethod
    async def confirm_match(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        bank_transaction_id: uuid.UUID,
        kind: str,
        payment_id: uuid.UUID,
    ) -> BankTransaction:
        """Confirma o vínculo de uma linha de extrato a um pagamento.

        Valida sinal (entrada↔invoice_payment, saída↔bill_payment), existência e
        igualdade exata de valor, e que o pagamento ainda não foi consumido.
        """
        if kind not in _KINDS:
            raise ReconciliationException(
                f"kind inválido: {kind!r}. Use {' ou '.join(_KINDS)}."
            )

        bt = (
            await db.execute(
                select(BankTransaction).where(
                    BankTransaction.tenant_id == tenant_id,
                    BankTransaction.id == bank_transaction_id,
                )
            )
        ).scalar_one_or_none()
        if bt is None:
            raise ReconciliationException(
                f"Transação bancária {bank_transaction_id} não encontrada."
            )
        if bt.reconciled:
            raise ReconciliationException(
                f"Transação bancária {bank_transaction_id} já está conciliada."
            )

        if kind == "invoice_payment":
            if bt.amount <= _ZERO:
                raise ReconciliationException(
                    "Entrada de extrato (valor > 0) casa com 'invoice_payment'; "
                    "esta linha é de saída."
                )
            expected = bt.amount
            pay_inv = (
                await db.execute(
                    select(InvoicePayment).where(
                        InvoicePayment.tenant_id == tenant_id,
                        InvoicePayment.id == payment_id,
                    )
                )
            ).scalar_one_or_none()
            pay_amount = pay_inv.amount if pay_inv is not None else None
        else:
            if bt.amount >= _ZERO:
                raise ReconciliationException(
                    "Saída de extrato (valor < 0) casa com 'bill_payment'; "
                    "esta linha é de entrada."
                )
            expected = -bt.amount
            pay_bill = (
                await db.execute(
                    select(BillPayment).where(
                        BillPayment.tenant_id == tenant_id,
                        BillPayment.id == payment_id,
                    )
                )
            ).scalar_one_or_none()
            pay_amount = pay_bill.amount if pay_bill is not None else None

        if pay_amount is None:
            raise ReconciliationException(
                f"Pagamento {payment_id} ({kind}) não encontrado."
            )
        if pay_amount != expected:
            raise ReconciliationException(
                f"Valor do pagamento ({pay_amount}) não bate com o extrato "
                f"({expected})."
            )

        consumed = await ReconciliationService._consumed_payment_ids(
            db, tenant_id, kind
        )
        if payment_id in consumed:
            raise ReconciliationException(
                f"Pagamento {payment_id} já está vinculado a outra conciliação."
            )

        bt.reconciled = True
        bt.matched_kind = kind
        bt.matched_payment_id = payment_id
        await db.flush()
        return bt

    @staticmethod
    async def auto_reconcile(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        start_date: date,
        end_date: date,
        date_tolerance_days: int = 3,
    ) -> dict[str, Any]:
        """Concilia automaticamente apenas os casos de candidato único.

        Linhas com 0 ou ≥2 candidatos ficam para conciliação manual. Pagamentos
        já usados nesta passada não são reaproveitados (evita match ambíguo).
        """
        suggestions = await ReconciliationService.suggest_matches(
            db, tenant_id, start_date, end_date, date_tolerance_days
        )
        consumed: set[uuid.UUID] = set()
        confirmed = 0
        for sug in suggestions:
            candidates = sug["candidates"]
            if len(candidates) != 1:
                continue
            candidate = candidates[0]
            payment_id: uuid.UUID = candidate["payment_id"]
            if payment_id in consumed:
                continue
            await ReconciliationService.confirm_match(
                db,
                tenant_id,
                sug["bank_transaction"]["id"],
                candidate["kind"],
                payment_id,
            )
            consumed.add(payment_id)
            confirmed += 1

        return {
            "unreconciled": len(suggestions),
            "auto_reconciled": confirmed,
            "pending": len(suggestions) - confirmed,
        }

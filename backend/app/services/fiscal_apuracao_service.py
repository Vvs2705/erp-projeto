"""Apuração tributária por período (RTC — CBS/IBS) sobre tributos persistidos.

Fluxo:

1. Para cada documento fiscal, ``record_document_taxes`` (ou
   ``determine_and_record``) persiste uma linha por tributo incidente, marcando
   ``direction`` = ``debit`` (saída/devido) ou ``credit`` (entrada/creditável).
2. ``assess_period`` apura um período somando ``débitos - créditos`` por tributo.
   Saldo positivo é valor a recolher; saldo negativo é crédito a transportar.

A determinação das alíquotas é delegada ao motor versão-por-vigência
(``fiscal_engine.determine``); este serviço cuida da persistência e da apuração.
"""

import uuid
from collections.abc import Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fiscal_engine import Operation, Regime, TaxResult, determine
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fiscal import FiscalDocumentTax

_CENTS = Decimal("0.01")
_ZERO = Decimal("0.00")
_VALID_DIRECTIONS = ("debit", "credit")
# Tributos da Reforma Tributária do Consumo apurados por padrão.
_RTC_TAXES: tuple[str, ...] = ("cbs", "ibs")


class FiscalApuracaoException(Exception):
    """Erro de apuração fiscal."""


class FiscalApuracaoService:
    @staticmethod
    async def record_document_taxes(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        document_type: str,
        document_id: uuid.UUID,
        document_number: str,
        direction: str,
        issue_date: date,
        tax_result: TaxResult,
    ) -> list[FiscalDocumentTax]:
        """Persiste uma linha por tributo incidente de um documento fiscal.

        ``direction`` deve ser ``debit`` (saída/devido) ou ``credit``
        (entrada/creditável). ``tax_result`` é a saída de ``fiscal_engine``.
        """
        if direction not in _VALID_DIRECTIONS:
            raise FiscalApuracaoException(
                f"direction inválida: {direction!r}. Use 'debit' ou 'credit'."
            )

        rows: list[FiscalDocumentTax] = []
        for line in tax_result.lines:
            row = FiscalDocumentTax(
                tenant_id=tenant_id,
                document_type=document_type,
                document_id=document_id,
                document_number=document_number,
                direction=direction,
                tax=line.tax,
                base=line.base,
                rate=line.rate,
                amount=line.amount,
                issue_date=issue_date,
            )
            db.add(row)
            rows.append(row)

        await db.flush()
        return rows

    @staticmethod
    async def determine_and_record(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        document_type: str,
        document_id: uuid.UUID,
        document_number: str,
        direction: str,
        base: Decimal,
        issue_date: date,
        operation: Operation = Operation.SALE_GOODS,
        regime: Regime = Regime.PRESUMIDO,
    ) -> list[FiscalDocumentTax]:
        """Determina os tributos pela vigência e persiste-os de uma vez."""
        tax_result = determine(base, issue_date, operation, regime)
        return await FiscalApuracaoService.record_document_taxes(
            db,
            tenant_id,
            document_type=document_type,
            document_id=document_id,
            document_number=document_number,
            direction=direction,
            issue_date=issue_date,
            tax_result=tax_result,
        )

    @staticmethod
    async def assess_period(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        start_date: date,
        end_date: date,
        *,
        taxes: Sequence[str] = _RTC_TAXES,
    ) -> dict[str, Any]:
        """Apura ``débitos - créditos`` por tributo no período ``[start, end]``.

        Para cada tributo devolve débito, crédito, saldo (débito - crédito),
        valor a recolher (saldo positivo) e crédito a transportar (saldo
        negativo). ``total_payable`` soma os valores a recolher.
        """
        if start_date > end_date:
            raise FiscalApuracaoException("start_date não pode ser maior que end_date.")

        tax_keys = tuple(taxes)
        if not tax_keys:
            raise FiscalApuracaoException("Informe ao menos um tributo para apurar.")

        stmt = (
            select(
                FiscalDocumentTax.tax,
                FiscalDocumentTax.direction,
                func.coalesce(func.sum(FiscalDocumentTax.amount), 0).label("total"),
            )
            .where(
                FiscalDocumentTax.tenant_id == tenant_id,
                FiscalDocumentTax.issue_date >= start_date,
                FiscalDocumentTax.issue_date <= end_date,
                FiscalDocumentTax.tax.in_(tax_keys),
            )
            .group_by(FiscalDocumentTax.tax, FiscalDocumentTax.direction)
        )
        result = await db.execute(stmt)

        sums: dict[str, dict[str, Decimal]] = {
            tax: {"debit": _ZERO, "credit": _ZERO} for tax in tax_keys
        }
        for row in result.all():
            amount = Decimal(str(row.total)).quantize(_CENTS, rounding=ROUND_HALF_UP)
            sums[row.tax][row.direction] = amount

        taxes_out: dict[str, dict[str, Decimal]] = {}
        total_payable = _ZERO
        for tax in tax_keys:
            debit = sums[tax]["debit"]
            credit = sums[tax]["credit"]
            balance = debit - credit
            payable = balance if balance > _ZERO else _ZERO
            carryforward = -balance if balance < _ZERO else _ZERO
            taxes_out[tax] = {
                "debit": debit,
                "credit": credit,
                "balance": balance,
                "payable": payable,
                "credit_carryforward": carryforward,
            }
            total_payable += payable

        return {
            "tenant_id": tenant_id,
            "start_date": start_date,
            "end_date": end_date,
            "taxes": taxes_out,
            "total_payable": total_payable,
        }

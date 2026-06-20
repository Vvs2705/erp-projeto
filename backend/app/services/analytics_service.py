"""Analytics / KPIs — indicadores gerenciais derivados do razão contábil.

Camada de BI que NÃO duplica os relatórios contábeis: compõe os resultados de
``ReportingService`` (DRE, Balanço, ageing) em indicadores e monta o fluxo de
caixa pelo **método direto** a partir das liquidações reais de contas a receber
(``InvoicePayment``) e a pagar (``BillPayment``). Sem dependência de credencial
externa; tudo apurado sobre dados já contabilizados.
"""

import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finance import BillPayment, InvoicePayment
from app.services.reporting_service import ReportingService

_ZERO = Decimal("0.0000")
_QUANT = Decimal("0.0001")


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
    """Razão segura: 0 quando o denominador é zero; 4 casas decimais."""
    if denominator == _ZERO:
        return _ZERO
    return (numerator / denominator).quantize(_QUANT, rounding=ROUND_HALF_UP)


class AnalyticsService:
    @staticmethod
    async def get_cash_flow(
        db: AsyncSession, tenant_id: uuid.UUID, start_date: date, end_date: date
    ) -> dict[str, Any]:
        """Fluxo de caixa (método direto) no período.

        Entradas = recebimentos de clientes (``InvoicePayment``); saídas =
        pagamentos a fornecedores (``BillPayment``), ambos pela ``payment_date``.
        Detalha também o total por meio de pagamento (PIX, boleto, etc.).
        """
        if end_date < start_date:
            raise ValueError("end_date não pode ser anterior a start_date")

        inflow_rows = (
            await db.execute(
                select(InvoicePayment.payment_method, InvoicePayment.amount).where(
                    InvoicePayment.tenant_id == tenant_id,
                    InvoicePayment.payment_date >= start_date,
                    InvoicePayment.payment_date <= end_date,
                )
            )
        ).all()
        outflow_rows = (
            await db.execute(
                select(BillPayment.payment_method, BillPayment.amount).where(
                    BillPayment.tenant_id == tenant_id,
                    BillPayment.payment_date >= start_date,
                    BillPayment.payment_date <= end_date,
                )
            )
        ).all()

        inflows_by_method: dict[str, Decimal] = {}
        total_inflows = _ZERO
        for row in inflow_rows:
            amount = Decimal(str(row.amount))
            inflows_by_method[row.payment_method] = (
                inflows_by_method.get(row.payment_method, _ZERO) + amount
            )
            total_inflows += amount

        outflows_by_method: dict[str, Decimal] = {}
        total_outflows = _ZERO
        for row in outflow_rows:
            amount = Decimal(str(row.amount))
            outflows_by_method[row.payment_method] = (
                outflows_by_method.get(row.payment_method, _ZERO) + amount
            )
            total_outflows += amount

        net_cash_flow = total_inflows - total_outflows

        return {
            "start_date": start_date,
            "end_date": end_date,
            "operating": {
                "receipts_from_customers": total_inflows,
                "payments_to_suppliers": total_outflows,
                "net_cash_from_operations": net_cash_flow,
            },
            "by_method": {
                "inflows": inflows_by_method,
                "outflows": outflows_by_method,
            },
            "net_cash_flow": net_cash_flow,
        }

    @staticmethod
    async def get_financial_kpis(
        db: AsyncSession, tenant_id: uuid.UUID, start_date: date, end_date: date
    ) -> dict[str, Any]:
        """Painel de KPIs gerenciais.

        Resultado do período (DRE) + posição patrimonial em ``end_date``
        (Balanço) + saldos em aberto de AR/AP (ageing), reduzidos a indicadores:
        margem líquida, endividamento, retornos (ROA/ROE) e capital de giro
        comercial líquido. Indicadores são razões seguras (0 se denominador 0).
        """
        if end_date < start_date:
            raise ValueError("end_date não pode ser anterior a start_date")

        dre = await ReportingService.get_income_statement(
            db, tenant_id, start_date, end_date
        )
        balance = await ReportingService.get_balance_sheet(db, tenant_id, end_date)
        ar = await ReportingService.get_ageing_report(db, tenant_id, "AR", end_date)
        ap = await ReportingService.get_ageing_report(db, tenant_id, "AP", end_date)

        gross_revenue: Decimal = dre["gross_revenue"]
        total_expenses: Decimal = dre["total_expenses"]
        net_result: Decimal = dre["net_result"]

        total_assets: Decimal = balance["totals"]["total_assets"]
        total_liabilities: Decimal = balance["totals"]["total_liabilities"]
        total_equity: Decimal = balance["totals"]["total_equity"]

        ar_open: Decimal = ar["summary"]["total_open"]
        ap_open: Decimal = ap["summary"]["total_open"]

        return {
            "period": {"start_date": start_date, "end_date": end_date},
            "result": {
                "gross_revenue": gross_revenue,
                "total_expenses": total_expenses,
                "net_result": net_result,
                "net_margin": _ratio(net_result, gross_revenue),
            },
            "position": {
                "total_assets": total_assets,
                "total_liabilities": total_liabilities,
                "total_equity": total_equity,
                "debt_ratio": _ratio(total_liabilities, total_assets),
                "equity_ratio": _ratio(total_equity, total_assets),
            },
            "returns": {
                "return_on_assets": _ratio(net_result, total_assets),
                "return_on_equity": _ratio(net_result, total_equity),
            },
            "working_capital": {
                "accounts_receivable_open": ar_open,
                "accounts_payable_open": ap_open,
                "net_working_capital": ar_open - ap_open,
            },
        }

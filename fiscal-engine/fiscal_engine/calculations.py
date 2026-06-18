"""Facade de compatibilidade sobre o motor de determinação versionado.

Mantém o contrato histórico de ``TaxEngine.calculate_taxes`` (dict com todas as
chaves de tributo + ``total_taxes``), mas toda a lógica passa pelo motor
versionado por vigência em :mod:`fiscal_engine.determination`.
"""

from datetime import date, datetime
from decimal import Decimal

from fiscal_engine.determination import Operation, Regime, determine

_ALL_TAXES = ("icms", "ipi", "pis", "cofins", "iss", "cbs", "ibs")


def _parse_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return datetime.fromisoformat(value).date()
    return value


class TaxEngine:
    @staticmethod
    def calculate_taxes(
        amount: Decimal | float | str | int,
        issue_date: date | datetime | str,
        is_service: bool = False,
    ) -> dict[str, Decimal]:
        """Calcula os tributos de um valor/data, delegando ao motor versionado.

        Retorna um dict com todas as chaves de tributo (zeradas quando não
        incidem) e ``total_taxes``. Usa Lucro Presumido (PIS/COFINS destacados)
        para preservar o comportamento histórico.
        """
        parsed_date = _parse_date(issue_date)
        operation = Operation.SALE_SERVICE if is_service else Operation.SALE_GOODS
        result = determine(amount, parsed_date, operation, Regime.PRESUMIDO)

        taxes: dict[str, Decimal] = {tax: Decimal("0.00") for tax in _ALL_TAXES}
        for line in result.lines:
            taxes[line.tax] = line.amount
        taxes["total_taxes"] = result.total_taxes
        return taxes

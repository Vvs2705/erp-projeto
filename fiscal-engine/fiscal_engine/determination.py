"""Motor de determinação tributária versionado por vigência (IP próprio).

As alíquotas são selecionadas pela **data de emissão** do documento (vigência),
nunca embutidas inline no código de negócio. Calcula os tributos clássicos
(ICMS, IPI, PIS, COFINS, ISS) e os tributos da Reforma Tributária do Consumo
(RTC) — CBS e IBS — cuja transição começa em 01/01/2026.

A transmissão à SEFAZ/municípios é delegada a um provedor especializado
(camada de emissão); este módulo faz apenas determinação/apuração.

A tabela ``_RATE_TABLE`` é o ponto de extensão: novas vigências (ex.: o ramp-up
de CBS/IBS de 2027 em diante) entram como novas ``RateSet`` efetivas por data,
sem tocar na lógica de cálculo.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

_CENTS = Decimal("0.01")
_ZERO = Decimal("0.00")


class Regime(str, Enum):
    SIMPLES = "simples_nacional"
    PRESUMIDO = "lucro_presumido"
    REAL = "lucro_real"


class Operation(str, Enum):
    SALE_GOODS = "sale_goods"
    SALE_SERVICE = "sale_service"


@dataclass(frozen=True)
class RateSet:
    """Conjunto de alíquotas vigente em um intervalo de datas."""

    effective_from: date
    effective_to: date | None  # None = vigente indefinidamente
    icms: Decimal
    ipi: Decimal
    pis: Decimal
    cofins: Decimal
    iss: Decimal
    cbs: Decimal
    ibs: Decimal


# Tabela versionada por vigência (ordem da mais antiga para a mais recente).
# CBS/IBS seguem o cronograma da RTC: 2026 é a fase de teste (CBS 0,9%, IBS 0,1%).
_RATE_TABLE: tuple[RateSet, ...] = (
    RateSet(
        effective_from=date(2000, 1, 1),
        effective_to=date(2025, 12, 31),
        icms=Decimal("0.18"),
        ipi=Decimal("0.05"),
        pis=Decimal("0.0165"),
        cofins=Decimal("0.076"),
        iss=Decimal("0.05"),
        cbs=_ZERO,
        ibs=_ZERO,
    ),
    RateSet(
        effective_from=date(2026, 1, 1),
        effective_to=None,
        icms=Decimal("0.18"),
        ipi=Decimal("0.05"),
        pis=Decimal("0.0165"),
        cofins=Decimal("0.076"),
        iss=Decimal("0.05"),
        cbs=Decimal("0.009"),
        ibs=Decimal("0.001"),
    ),
)


@dataclass(frozen=True)
class TaxLine:
    tax: str
    base: Decimal
    rate: Decimal
    amount: Decimal


@dataclass(frozen=True)
class TaxResult:
    issue_date: date
    operation: Operation
    regime: Regime
    base: Decimal
    lines: tuple[TaxLine, ...]

    @property
    def total_taxes(self) -> Decimal:
        total = _ZERO
        for line in self.lines:
            total += line.amount
        return total

    def as_dict(self) -> dict[str, Decimal]:
        """Mapa ``tributo -> valor`` (apenas os tributos incidentes)."""
        result = {line.tax: line.amount for line in self.lines}
        result["total_taxes"] = self.total_taxes
        return result


def select_rate_set(
    issue_date: date, table: Sequence[RateSet] = _RATE_TABLE
) -> RateSet:
    """Seleciona o conjunto de alíquotas vigente na ``issue_date``."""
    for rate_set in table:
        within_start = rate_set.effective_from <= issue_date
        within_end = rate_set.effective_to is None or issue_date <= rate_set.effective_to
        if within_start and within_end:
            return rate_set
    raise ValueError(f"Nenhuma vigência de alíquotas definida para {issue_date}.")


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def determine(
    base: Decimal | str | float | int,
    issue_date: date,
    operation: Operation = Operation.SALE_GOODS,
    regime: Regime = Regime.PRESUMIDO,
    *,
    table: Sequence[RateSet] = _RATE_TABLE,
) -> TaxResult:
    """Determina os tributos de um documento pela vigência da data de emissão.

    - Mercadoria: ICMS, IPI (+ PIS/COFINS fora do Simples).
    - Serviço: ISS (+ PIS/COFINS fora do Simples).
    - CBS/IBS (RTC) incidem a partir da vigência, para ambas as operações.
    No Simples Nacional, PIS/COFINS não são destacados (recolhidos via DAS).
    """
    base_dec = Decimal(str(base))
    if base_dec < _ZERO:
        raise ValueError("Base de cálculo não pode ser negativa.")
    rate_set = select_rate_set(issue_date, table)

    lines: list[TaxLine] = []

    def add(tax: str, rate: Decimal) -> None:
        if rate > _ZERO:
            lines.append(
                TaxLine(tax=tax, base=base_dec, rate=rate, amount=_money(base_dec * rate))
            )

    if operation == Operation.SALE_SERVICE:
        add("iss", rate_set.iss)
    else:
        add("icms", rate_set.icms)
        add("ipi", rate_set.ipi)

    if regime != Regime.SIMPLES:
        add("pis", rate_set.pis)
        add("cofins", rate_set.cofins)

    add("cbs", rate_set.cbs)
    add("ibs", rate_set.ibs)

    return TaxResult(
        issue_date=issue_date,
        operation=operation,
        regime=regime,
        base=base_dec,
        lines=tuple(lines),
    )

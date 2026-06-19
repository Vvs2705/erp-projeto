"""Camada de emissão fiscal: estruturas do documento + montagem do payload.

A determinação dos tributos é feita por :mod:`fiscal_engine.determination`. A
ASSINATURA digital (ICP-Brasil) e a TRANSMISSÃO à SEFAZ/municípios são
delegadas a um provedor especializado (ex.: Focus NFe / PlugNotas). Este módulo
NÃO gera nem assina XML — monta um payload estruturado e neutro que o cliente
concreto do provedor consome.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from fiscal_engine.determination import Operation, TaxResult


@dataclass(frozen=True)
class Party:
    cnpj: str
    name: str


@dataclass(frozen=True)
class Item:
    code: str
    description: str
    ncm: str
    cfop: str
    quantity: Decimal
    unit_value: Decimal

    @property
    def total(self) -> Decimal:
        return self.quantity * self.unit_value


@dataclass(frozen=True)
class EmissionRequest:
    issuer: Party
    recipient: Party
    operation: Operation
    issue_date: date
    nature: str
    items: tuple[Item, ...]


@dataclass(frozen=True)
class EmissionResult:
    provider: str
    status: str
    protocol: str | None
    access_key: str | None
    raw: dict[str, object]


def total_amount(request: EmissionRequest) -> Decimal:
    total = Decimal("0.00")
    for item in request.items:
        total += item.total
    return total


def build_provider_payload(
    request: EmissionRequest, taxes: TaxResult
) -> dict[str, object]:
    """Monta o payload neutro de provedor a partir do documento + determinação."""
    return {
        "operacao": request.operation.value,
        "natureza_operacao": request.nature,
        "data_emissao": request.issue_date.isoformat(),
        "emitente": {"cnpj": request.issuer.cnpj, "nome": request.issuer.name},
        "destinatario": {
            "cnpj": request.recipient.cnpj,
            "nome": request.recipient.name,
        },
        "itens": [
            {
                "codigo": item.code,
                "descricao": item.description,
                "ncm": item.ncm,
                "cfop": item.cfop,
                "quantidade": str(item.quantity),
                "valor_unitario": str(item.unit_value),
                "valor_total": str(item.total),
            }
            for item in request.items
        ],
        "valor_total": str(total_amount(request)),
        "tributos": {tax: str(value) for tax, value in taxes.as_dict().items()},
    }

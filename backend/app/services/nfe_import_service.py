"""Importação/extração de NF-e (modelo 55) a partir do XML.

Fina camada sobre :mod:`fiscal_engine.nfe` (parser puro, compartilhável com o
FiscWise): faz o parse determinístico e serializa para um ``dict`` neutro pronto
para a API/UI. Não persiste nada — extração e conferência; a criação de contas a
pagar a partir da nota fica a cargo do fluxo de AP existente.
"""

from typing import Any

from fiscal_engine.nfe import ParsedNFe, parse_nfe


class NFeImportService:
    @staticmethod
    def parse(xml: str) -> dict[str, Any]:
        """Faz o parse do XML da NF-e e devolve a estrutura serializável.

        Propaga :class:`fiscal_engine.nfe.NFeParseError` (subclasse de
        ``ValueError``) em XML inválido — o router a converte em HTTP 400.
        """
        return NFeImportService._serialize(parse_nfe(xml))

    @staticmethod
    def _serialize(nfe: ParsedNFe) -> dict[str, Any]:
        return {
            "access_key": nfe.access_key,
            "model": nfe.model,
            "number": nfe.number,
            "series": nfe.series,
            "issue_date": nfe.issue_date,
            "emitter": {"tax_id": nfe.emitter.tax_id, "name": nfe.emitter.name},
            "recipient": {
                "tax_id": nfe.recipient.tax_id,
                "name": nfe.recipient.name,
            },
            "totals": {
                "products": nfe.totals.products,
                "discount": nfe.totals.discount,
                "freight": nfe.totals.freight,
                "icms": nfe.totals.icms,
                "ipi": nfe.totals.ipi,
                "pis": nfe.totals.pis,
                "cofins": nfe.totals.cofins,
                "invoice_total": nfe.totals.invoice_total,
            },
            "items": [
                {
                    "number": item.number,
                    "code": item.code,
                    "description": item.description,
                    "ncm": item.ncm,
                    "cfop": item.cfop,
                    "unit": item.unit,
                    "quantity": item.quantity,
                    "unit_value": item.unit_value,
                    "total_value": item.total_value,
                }
                for item in nfe.items
            ],
        }

"""Parser determinístico de NF-e (modelo 55) — layout SEFAZ 4.00.

A NF-e é um XML estruturado e padronizado pela SEFAZ; extrair seus dados é
DETERMINÍSTICO (não exige IA). Este módulo lê o XML (com ou sem o invólucro
``nfeProc``) e devolve uma estrutura tipada e neutra — emitente, destinatário,
itens (com NCM/CFOP/quantidades/valores) e totais — pronta para alimentar o
fluxo de contas a pagar ou conferência fiscal.

A camada de IA (OCR de DANFE em PDF/imagem, match difuso) é outra história; aqui
tudo vem de campos nomeados do próprio XML, então é auditável e reprodutível.

Pertence ao ``fiscal-engine`` (pacote Python puro) para ser compartilhável com o
FiscWise, junto de :mod:`fiscal_engine.determination` e :mod:`fiscal_engine.emission`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree as ET

_ZERO = Decimal("0.00")


class NFeParseError(ValueError):
    """XML de NF-e inválido ou com campos obrigatórios ausentes."""


@dataclass(frozen=True)
class NFeParty:
    tax_id: str  # CNPJ ou CPF (somente dígitos, como no XML)
    name: str


@dataclass(frozen=True)
class NFeItem:
    number: int
    code: str
    description: str
    ncm: str
    cfop: str
    unit: str
    quantity: Decimal
    unit_value: Decimal
    total_value: Decimal


@dataclass(frozen=True)
class NFeTotals:
    products: Decimal
    discount: Decimal
    freight: Decimal
    icms: Decimal
    ipi: Decimal
    pis: Decimal
    cofins: Decimal
    invoice_total: Decimal


@dataclass(frozen=True)
class ParsedNFe:
    access_key: str
    model: str
    number: str
    series: str
    issue_date: date
    emitter: NFeParty
    recipient: NFeParty
    totals: NFeTotals
    items: list[NFeItem] = field(default_factory=list)


def _local(tag: str) -> str:
    """Nome local da tag, sem o namespace (``{ns}prod`` -> ``prod``)."""
    return tag.rsplit("}", 1)[-1]


def _ns(tag: str) -> str:
    """Prefixo de namespace de uma tag (``{ns}prod`` -> ``{ns}``; '' se ausente)."""
    return tag[: tag.index("}") + 1] if "}" in tag else ""


def _text(parent: ET.Element, ns: str, name: str) -> str | None:
    child = parent.find(f"{ns}{name}")
    if child is None or child.text is None:
        return None
    return child.text.strip()


def _required_text(parent: ET.Element, ns: str, name: str, where: str) -> str:
    value = _text(parent, ns, name)
    if value is None or value == "":
        raise NFeParseError(f"Campo obrigatório ausente: <{name}> em {where}.")
    return value


def _decimal(parent: ET.Element, ns: str, name: str, default: Decimal = _ZERO) -> Decimal:
    raw = _text(parent, ns, name)
    if raw is None or raw == "":
        return default
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise NFeParseError(f"Valor numérico inválido em <{name}>: {raw!r}.") from exc


def _party(inf: ET.Element, ns: str, tag: str) -> NFeParty:
    node = inf.find(f"{ns}{tag}")
    if node is None:
        raise NFeParseError(f"Bloco obrigatório ausente: <{tag}>.")
    # Emitente é sempre CNPJ; destinatário pode ser CNPJ ou CPF.
    tax_id = _text(node, ns, "CNPJ") or _text(node, ns, "CPF")
    if not tax_id:
        raise NFeParseError(f"<{tag}> sem CNPJ/CPF.")
    name = _required_text(node, ns, "xNome", f"<{tag}>")
    return NFeParty(tax_id=tax_id, name=name)


def _issue_date(ide: ET.Element, ns: str) -> date:
    # 4.00 usa <dhEmi> (datetime ISO); layouts antigos usam <dEmi> (date).
    raw = _text(ide, ns, "dhEmi") or _text(ide, ns, "dEmi")
    if not raw:
        raise NFeParseError("Data de emissão ausente (<dhEmi>/<dEmi>).")
    try:
        return date.fromisoformat(raw[:10])
    except ValueError as exc:
        raise NFeParseError(f"Data de emissão inválida: {raw!r}.") from exc


def _access_key(inf: ET.Element) -> str:
    raw = inf.get("Id", "")
    digits = raw[3:] if raw.startswith("NFe") else raw
    if len(digits) != 44 or not digits.isdigit():
        raise NFeParseError(
            f"Chave de acesso inválida no atributo Id: {raw!r} (esperado NFe+44 dígitos)."
        )
    return digits


def parse_nfe(xml: str) -> ParsedNFe:
    """Lê o XML de uma NF-e e devolve sua representação estruturada.

    Aceita o XML com o invólucro ``<nfeProc>`` (retorno autorizado da SEFAZ) ou a
    ``<NFe>`` isolada. Levanta :class:`NFeParseError` em XML malformado ou com
    campos obrigatórios faltando.
    """
    # Defesa contra XXE / billion-laughs: a NF-e nunca declara DOCTYPE/ENTITY,
    # então recusamos esses construtos antes de entregar ao parser da stdlib
    # (que sozinho expandiria entidades). Sem dependência externa.
    lowered = xml.lstrip()[:4096].lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise NFeParseError("XML com DOCTYPE/ENTITY não é aceito em NF-e.")

    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise NFeParseError(f"XML malformado: {exc}") from exc

    ns = _ns(root.tag)
    root_local = _local(root.tag)
    if root_local == "nfeProc":
        nfe = root.find(f"{ns}NFe")
    elif root_local == "NFe":
        nfe = root
    else:
        nfe = None
    if nfe is None:
        raise NFeParseError("XML não contém o elemento <NFe>.")

    inf = nfe.find(f"{ns}infNFe")
    if inf is None:
        raise NFeParseError("XML não contém o elemento <infNFe>.")

    ide = inf.find(f"{ns}ide")
    if ide is None:
        raise NFeParseError("Bloco obrigatório ausente: <ide>.")

    emitter = _party(inf, ns, "emit")
    recipient = _party(inf, ns, "dest")

    items: list[NFeItem] = []
    for det in inf.findall(f"{ns}det"):
        prod = det.find(f"{ns}prod")
        if prod is None:
            continue
        n_item = det.get("nItem", "0")
        try:
            number = int(n_item)
        except ValueError as exc:
            raise NFeParseError(f"nItem inválido: {n_item!r}.") from exc
        items.append(
            NFeItem(
                number=number,
                code=_required_text(prod, ns, "cProd", "<prod>"),
                description=_required_text(prod, ns, "xProd", "<prod>"),
                ncm=_text(prod, ns, "NCM") or "",
                cfop=_text(prod, ns, "CFOP") or "",
                unit=_text(prod, ns, "uCom") or "",
                quantity=_decimal(prod, ns, "qCom"),
                unit_value=_decimal(prod, ns, "vUnCom"),
                total_value=_decimal(prod, ns, "vProd"),
            )
        )

    if not items:
        raise NFeParseError("NF-e sem itens (<det>/<prod>).")

    icms_tot = inf.find(f"{ns}total/{ns}ICMSTot")
    if icms_tot is None:
        raise NFeParseError("Bloco obrigatório ausente: <total><ICMSTot>.")

    totals = NFeTotals(
        products=_decimal(icms_tot, ns, "vProd"),
        discount=_decimal(icms_tot, ns, "vDesc"),
        freight=_decimal(icms_tot, ns, "vFrete"),
        icms=_decimal(icms_tot, ns, "vICMS"),
        ipi=_decimal(icms_tot, ns, "vIPI"),
        pis=_decimal(icms_tot, ns, "vPIS"),
        cofins=_decimal(icms_tot, ns, "vCOFINS"),
        invoice_total=_decimal(icms_tot, ns, "vNF"),
    )

    return ParsedNFe(
        access_key=_access_key(inf),
        model=_required_text(ide, ns, "mod", "<ide>"),
        number=_required_text(ide, ns, "nNF", "<ide>"),
        series=_text(ide, ns, "serie") or "",
        issue_date=_issue_date(ide, ns),
        emitter=emitter,
        recipient=recipient,
        totals=totals,
        items=items,
    )

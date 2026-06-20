"""Testes do parser determinístico de NF-e (``fiscal_engine.nfe``) e do serviço.

Cobre o layout 4.00 com namespace e invólucro ``nfeProc``, a ``NFe`` isolada, e
as rejeições (sem itens, malformado, DOCTYPE/ENTITY, chave inválida).
"""

from datetime import date
from decimal import Decimal

import pytest
from fiscal_engine.nfe import NFeParseError, parse_nfe

from app.services.nfe_import_service import NFeImportService

# 44 dígitos: NFe + chave de acesso.
ACCESS_KEY = "35260614200166000187550010000001231000000125"

NFE_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
  <NFe>
    <infNFe versao="4.00" Id="NFe{ACCESS_KEY}">
      <ide>
        <cUF>35</cUF>
        <mod>55</mod>
        <serie>1</serie>
        <nNF>123</nNF>
        <dhEmi>2026-06-10T10:30:00-03:00</dhEmi>
      </ide>
      <emit>
        <CNPJ>14200166000187</CNPJ>
        <xNome>Fornecedor Industria LTDA</xNome>
      </emit>
      <dest>
        <CNPJ>12345678000199</CNPJ>
        <xNome>Comprador Comercio LTDA</xNome>
      </dest>
      <det nItem="1">
        <prod>
          <cProd>SKU-001</cProd>
          <xProd>Parafuso M6</xProd>
          <NCM>73181500</NCM>
          <CFOP>5102</CFOP>
          <uCom>UN</uCom>
          <qCom>100.0000</qCom>
          <vUnCom>0.5000</vUnCom>
          <vProd>50.00</vProd>
        </prod>
      </det>
      <det nItem="2">
        <prod>
          <cProd>SKU-002</cProd>
          <xProd>Porca M6</xProd>
          <NCM>73181600</NCM>
          <CFOP>5102</CFOP>
          <uCom>UN</uCom>
          <qCom>100.0000</qCom>
          <vUnCom>0.3000</vUnCom>
          <vProd>30.00</vProd>
        </prod>
      </det>
      <total>
        <ICMSTot>
          <vProd>80.00</vProd>
          <vDesc>0.00</vDesc>
          <vFrete>5.00</vFrete>
          <vICMS>14.40</vICMS>
          <vIPI>0.00</vIPI>
          <vPIS>1.32</vPIS>
          <vCOFINS>6.08</vCOFINS>
          <vNF>85.00</vNF>
        </ICMSTot>
      </total>
    </infNFe>
  </NFe>
</nfeProc>"""


def test_parse_nfe_completa():
    nfe = parse_nfe(NFE_XML)
    assert nfe.access_key == ACCESS_KEY
    assert nfe.model == "55"
    assert nfe.number == "123"
    assert nfe.series == "1"
    assert nfe.issue_date == date(2026, 6, 10)

    assert nfe.emitter.tax_id == "14200166000187"
    assert nfe.emitter.name == "Fornecedor Industria LTDA"
    assert nfe.recipient.tax_id == "12345678000199"

    assert len(nfe.items) == 2
    item = nfe.items[0]
    assert item.number == 1
    assert item.code == "SKU-001"
    assert item.description == "Parafuso M6"
    assert item.ncm == "73181500"
    assert item.cfop == "5102"
    assert item.quantity == Decimal("100.0000")
    assert item.unit_value == Decimal("0.5000")
    assert item.total_value == Decimal("50.00")

    assert nfe.totals.products == Decimal("80.00")
    assert nfe.totals.freight == Decimal("5.00")
    assert nfe.totals.icms == Decimal("14.40")
    assert nfe.totals.invoice_total == Decimal("85.00")


def test_parse_nfe_isolada_sem_nfeproc():
    # Apenas <NFe>...</NFe>, sem o invólucro nfeProc.
    inner = NFE_XML[NFE_XML.index("<NFe>") : NFE_XML.index("</NFe>") + len("</NFe>")]
    xml = '<NFe xmlns="http://www.portalfiscal.inf.br/nfe">' + inner[len("<NFe>") :]
    nfe = parse_nfe(xml)
    assert nfe.number == "123"
    assert len(nfe.items) == 2


def test_parse_nfe_sem_itens_falha():
    xml = NFE_XML.replace(
        NFE_XML[NFE_XML.index("<det nItem") : NFE_XML.rindex("</det>") + len("</det>")],
        "",
    )
    with pytest.raises(NFeParseError):
        parse_nfe(xml)


def test_parse_xml_malformado_falha():
    with pytest.raises(NFeParseError):
        parse_nfe("<nfeProc><NFe>quebrado")


def test_parse_rejeita_doctype():
    # Defesa XXE / billion-laughs.
    malicious = (
        '<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY x "y">]>'
        + NFE_XML[NFE_XML.index("<nfeProc") :]
    )
    with pytest.raises(NFeParseError, match="DOCTYPE"):
        parse_nfe(malicious)


def test_parse_chave_invalida_falha():
    xml = NFE_XML.replace(f'Id="NFe{ACCESS_KEY}"', 'Id="NFe123"')
    with pytest.raises(NFeParseError, match="[Cc]have"):
        parse_nfe(xml)


def test_service_serializa_para_dict():
    data = NFeImportService.parse(NFE_XML)
    assert data["access_key"] == ACCESS_KEY
    assert data["number"] == "123"
    assert data["emitter"]["name"] == "Fornecedor Industria LTDA"
    assert len(data["items"]) == 2
    assert data["items"][1]["code"] == "SKU-002"
    assert data["totals"]["invoice_total"] == Decimal("85.00")

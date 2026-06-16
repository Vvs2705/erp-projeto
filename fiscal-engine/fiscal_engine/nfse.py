import xml.etree.ElementTree as ET
from decimal import Decimal
from datetime import date
from typing import Dict, Any

def generate_nfse_xml(
    tx_id: str,
    number: str,
    issuer_cnpj: str,
    dest_cnpj: str,
    amount: Any,
    taxes: Dict[str, Decimal],
    issue_date: date
) -> str:
    """
    Generates a basic XML representation of a Brazilian Service Invoice (NFS-e) matching standard formats (e.g. ABRASF/National).
    """
    amount_dec = Decimal(str(amount))
    
    # Root element
    root = ET.Element("EnviarLoteRpsEnvio", xmlns="http://www.abrasf.org.br/nfse.xsd")
    lote = ET.SubElement(root, "LoteRps", Id=f"Lote{tx_id}")
    ET.SubElement(lote, "NumeroLote").text = "1"
    ET.SubElement(lote, "Cnpj").text = issuer_cnpj
    ET.SubElement(lote, "InscricaoMunicipal").text = "123456"
    ET.SubElement(lote, "QuantidadeRps").text = "1"
    
    lista_rps = ET.SubElement(lote, "ListaRps")
    rps = ET.SubElement(lista_rps, "Rps")
    inf_declaracao = ET.SubElement(rps, "InfDeclaracaoPrestacaoServico", Id=f"Rps{number}")
    
    # Rps Identification
    ident_rps = ET.SubElement(inf_declaracao, "Rps")
    ident = ET.SubElement(ident_rps, "IdentificacaoRps")
    ET.SubElement(ident, "Numero").text = str(number)
    ET.SubElement(ident, "Serie").text = "A"
    ET.SubElement(ident, "Tipo").text = "1"  # RPS
    
    ET.SubElement(inf_declaracao, "DataEmissao").text = issue_date.isoformat()
    ET.SubElement(inf_declaracao, "Status").text = "1"  # Normal
    
    # Service block
    servico = ET.SubElement(inf_declaracao, "Servico")
    valores = ET.SubElement(servico, "Valores")
    ET.SubElement(valores, "ValorServicos").text = str(amount_dec)
    ET.SubElement(valores, "ValorIss").text = str(taxes.get("iss", Decimal("0.00")))
    ET.SubElement(valores, "Aliquota").text = "5.00"
    
    # CBS and IBS reform transition taxes (2026+)
    if taxes.get("cbs", Decimal("0.00")) > 0 or taxes.get("ibs", Decimal("0.00")) > 0:
        reforma = ET.SubElement(valores, "ReformaTributaria")
        ET.SubElement(reforma, "ValorCBS").text = str(taxes.get("cbs", Decimal("0.00")))
        ET.SubElement(reforma, "ValorIBS").text = str(taxes.get("ibs", Decimal("0.00")))
        
    ET.SubElement(servico, "ItemListaServico").text = "01.01"
    ET.SubElement(servico, "CodigoTributacaoMunicipio").text = "1234"
    ET.SubElement(servico, "Discriminacao").text = "PRESTACAO DE SERVICOS ERP"
    ET.SubElement(servico, "CodigoMunicipio").text = "3550308"  # São Paulo
    
    # Prestador (issuer)
    prestador = ET.SubElement(inf_declaracao, "Prestador")
    ET.SubElement(prestador, "Cnpj").text = issuer_cnpj
    ET.SubElement(prestador, "InscricaoMunicipal").text = "123456"
    
    # Tomador (receiver)
    tomador = ET.SubElement(inf_declaracao, "Tomador")
    ident_tomador = ET.SubElement(tomador, "IdentificacaoTomador")
    cpf_cnpj = ET.SubElement(ident_tomador, "CpfCnpj")
    ET.SubElement(cpf_cnpj, "Cnpj").text = dest_cnpj
    
    return ET.tostring(root, encoding="utf-8").decode("utf-8")

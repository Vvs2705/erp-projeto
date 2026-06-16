import xml.etree.ElementTree as ET
from decimal import Decimal
from datetime import date
from typing import Dict, Any

def generate_nfe_xml(
    tx_id: str,
    number: str,
    issuer_cnpj: str,
    dest_cnpj: str,
    amount: Any,
    taxes: Dict[str, Decimal],
    issue_date: date
) -> str:
    """
    Generates a basic XML representation of a Brazilian Product Invoice (NF-e) under layout 4.00.
    """
    amount_dec = Decimal(str(amount))
    
    # Root element
    root = ET.Element("NFe", xmlns="http://www.portalfiscal.inf.br/nfe")
    inf_nfe = ET.SubElement(root, "infNFe", Id=f"NFe{tx_id}", versao="4.00")
    
    # Identification
    ide = ET.SubElement(inf_nfe, "ide")
    ET.SubElement(ide, "cUF").text = "35"  # São Paulo
    ET.SubElement(ide, "cNF").text = "00001234"
    ET.SubElement(ide, "natOp").text = "VENDA MERCADORIA"
    ET.SubElement(ide, "mod").text = "55"
    ET.SubElement(ide, "serie").text = "1"
    ET.SubElement(ide, "nNF").text = str(number)
    ET.SubElement(ide, "dhEmi").text = issue_date.isoformat()
    
    # Issuer
    emit = ET.SubElement(inf_nfe, "emit")
    ET.SubElement(emit, "CNPJ").text = issuer_cnpj
    ET.SubElement(emit, "xNome").text = "EMISSOR EXEMPLO SA"
    
    # Receiver
    dest = ET.SubElement(inf_nfe, "dest")
    ET.SubElement(dest, "CNPJ").text = dest_cnpj
    ET.SubElement(dest, "xNome").text = "CLIENTE EXEMPLO SA"
    
    # Details (items)
    det = ET.SubElement(inf_nfe, "det", nItem="1")
    prod = ET.SubElement(det, "prod")
    ET.SubElement(prod, "cProd").text = "999"
    ET.SubElement(prod, "xProd").text = "PRODUTO TESTE ERP"
    ET.SubElement(prod, "NCM").text = "12345678"
    ET.SubElement(prod, "CFOP").text = "5102"
    ET.SubElement(prod, "uCom").text = "UN"
    ET.SubElement(prod, "qCom").text = "1.0000"
    ET.SubElement(prod, "vUnCom").text = str(amount_dec)
    ET.SubElement(prod, "vProd").text = str(amount_dec)
    
    imposto = ET.SubElement(det, "imposto")
    
    # ICMS details
    icms = ET.SubElement(imposto, "ICMS")
    icms00 = ET.SubElement(icms, "ICMS00")
    ET.SubElement(icms00, "orig").text = "0"
    ET.SubElement(icms00, "CST").text = "00"
    ET.SubElement(icms00, "vBC").text = str(amount_dec)
    ET.SubElement(icms00, "pICMS").text = "18.00"
    ET.SubElement(icms00, "vICMS").text = str(taxes.get("icms", Decimal("0.00")))
    
    # IPI details
    ipi = ET.SubElement(imposto, "IPI")
    ET.SubElement(ipi, "cEnq").text = "999"
    ipitrib = ET.SubElement(ipi, "IPITrib")
    ET.SubElement(ipitrib, "CST").text = "50"
    ET.SubElement(ipitrib, "vBC").text = str(amount_dec)
    ET.SubElement(ipitrib, "pIPI").text = "5.00"
    ET.SubElement(ipitrib, "vIPI").text = str(taxes.get("ipi", Decimal("0.00")))
    
    # PIS details
    pis = ET.SubElement(imposto, "PIS")
    pis_aliq = ET.SubElement(pis, "PISAliq")
    ET.SubElement(pis_aliq, "CST").text = "01"
    ET.SubElement(pis_aliq, "vBC").text = str(amount_dec)
    ET.SubElement(pis_aliq, "pPIS").text = "1.65"
    ET.SubElement(pis_aliq, "vPIS").text = str(taxes.get("pis", Decimal("0.00")))
    
    # COFINS details
    cofins = ET.SubElement(imposto, "COFINS")
    cofins_aliq = ET.SubElement(cofins, "COFINSAliq")
    ET.SubElement(cofins_aliq, "CST").text = "01"
    ET.SubElement(cofins_aliq, "vBC").text = str(amount_dec)
    ET.SubElement(cofins_aliq, "pCOFINS").text = "7.60"
    ET.SubElement(cofins_aliq, "vCOFINS").text = str(taxes.get("cofins", Decimal("0.00")))
    
    # CBS and IBS reform transition taxes (2026+)
    if taxes.get("cbs", Decimal("0.00")) > 0 or taxes.get("ibs", Decimal("0.00")) > 0:
        reforma = ET.SubElement(imposto, "ReformaTributaria")
        ET.SubElement(reforma, "vBC").text = str(amount_dec)
        ET.SubElement(reforma, "vCBS").text = str(taxes.get("cbs", Decimal("0.00")))
        ET.SubElement(reforma, "vIBS").text = str(taxes.get("ibs", Decimal("0.00")))

    # Total block
    total = ET.SubElement(inf_nfe, "total")
    icms_tot = ET.SubElement(total, "ICMSTot")
    ET.SubElement(icms_tot, "vBC").text = str(amount_dec)
    ET.SubElement(icms_tot, "vICMS").text = str(taxes.get("icms", Decimal("0.00")))
    ET.SubElement(icms_tot, "vIPI").text = str(taxes.get("ipi", Decimal("0.00")))
    ET.SubElement(icms_tot, "vPIS").text = str(taxes.get("pis", Decimal("0.00")))
    ET.SubElement(icms_tot, "vCOFINS").text = str(taxes.get("cofins", Decimal("0.00")))
    if taxes.get("cbs", Decimal("0.00")) > 0 or taxes.get("ibs", Decimal("0.00")) > 0:
        ET.SubElement(icms_tot, "vCBS").text = str(taxes.get("cbs", Decimal("0.00")))
        ET.SubElement(icms_tot, "vIBS").text = str(taxes.get("ibs", Decimal("0.00")))
    ET.SubElement(icms_tot, "vNF").text = str(amount_dec)
    
    return ET.tostring(root, encoding="utf-8").decode("utf-8")

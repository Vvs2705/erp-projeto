import uuid
from datetime import date
from decimal import Decimal
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from fiscal_engine.calculations import TaxEngine
from fiscal_engine.nfe import generate_nfe_xml
from fiscal_engine.nfse import generate_nfse_xml
from fiscal_engine.certificates import MockCertificateSigner

router = APIRouter(prefix="/api/v1/fiscal", tags=["Fiscal Engine"])

class TaxCalculationRequest(BaseModel):
    amount: Decimal
    issue_date: date
    is_service: bool = False

class XmlGenerationRequest(BaseModel):
    tx_id: str
    number: str
    issuer_cnpj: str
    dest_cnpj: str
    amount: Decimal
    issue_date: date
    is_service: bool = False
    pfx_password: str = "secret123"

@router.post("/calculate", status_code=status.HTTP_200_OK)
async def calculate_taxes(payload: TaxCalculationRequest):
    """
    Computes Brazilian taxes for a given amount and emission date.
    Calculates CBS and IBS if issue_date is >= 2026-01-01.
    """
    try:
        taxes = TaxEngine.calculate_taxes(
            amount=payload.amount,
            issue_date=payload.issue_date,
            is_service=payload.is_service
        )
        return taxes
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.post("/generate-xml", status_code=status.HTTP_200_OK)
async def generate_and_sign_xml(payload: XmlGenerationRequest):
    """
    Generates and digitally signs the NF-e or NFS-e XML.
    """
    try:
        # Calculate taxes
        taxes = TaxEngine.calculate_taxes(
            amount=payload.amount,
            issue_date=payload.issue_date,
            is_service=payload.is_service
        )
        
        # Generate XML structure
        if payload.is_service:
            xml_str = generate_nfse_xml(
                tx_id=payload.tx_id,
                number=payload.number,
                issuer_cnpj=payload.issuer_cnpj,
                dest_cnpj=payload.dest_cnpj,
                amount=payload.amount,
                taxes=taxes,
                issue_date=payload.issue_date
            )
            tag_to_sign = "InfDeclaracaoPrestacaoServico"
        else:
            xml_str = generate_nfe_xml(
                tx_id=payload.tx_id,
                number=payload.number,
                issuer_cnpj=payload.issuer_cnpj,
                dest_cnpj=payload.dest_cnpj,
                amount=payload.amount,
                taxes=taxes,
                issue_date=payload.issue_date
            )
            tag_to_sign = "infNFe"
            
        # Sign XML using the MockCertificateSigner
        signer = MockCertificateSigner(pfx_data=b"MOCK_PFX_BYTES_ERP", password=payload.pfx_password)
        signed_xml = signer.sign_xml(xml_str, tag_to_sign=tag_to_sign)
        
        return {
            "xml": signed_xml,
            "taxes": taxes
        }
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

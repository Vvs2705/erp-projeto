import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_tenant_and_user
from app.services.migration_service import MigrationService
from app.services.nfe_import_service import NFeImportService

router = APIRouter(prefix="/api/v1/migration", tags=["Migration"])


class CsvImportRequest(BaseModel):
    csv_content: str


class OfxImportRequest(BaseModel):
    ofx_content: str


class NfeXmlImportRequest(BaseModel):
    xml_content: str


@router.post("/partners/csv", status_code=status.HTTP_201_CREATED)
async def import_partners_csv(
    payload: CsvImportRequest,
    db: AsyncSession = Depends(get_db),
    tenant_and_user: tuple[uuid.UUID, uuid.UUID] = Depends(get_current_tenant_and_user),
) -> dict[str, Any]:
    tenant_id, _ = tenant_and_user
    try:
        partners = await MigrationService.import_partners_csv(
            db, tenant_id, payload.csv_content
        )
        await db.commit()
        return {
            "status": "success",
            "message": (
                f"Successfully parsed and imported/updated {len(partners)} partners."
            ),
            "partners": [
                {"id": p.id, "name": p.name, "cnpj": p.cnpj, "type": p.type}
                for p in partners
            ],
        }
    except ValueError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        ) from e


@router.post("/nfe/xml")
async def import_nfe_xml(
    payload: NfeXmlImportRequest,
    _tenant_and_user: tuple[uuid.UUID, uuid.UUID] = Depends(
        get_current_tenant_and_user
    ),
) -> dict[str, Any]:
    """Extrai os dados de uma NF-e (modelo 55) do XML — determinístico, sem IA.

    Exige autenticação (como todas as rotas ``/api``) mas não usa o tenant: a
    extração não persiste nada — devolve a estrutura (emitente, destinatário,
    itens e totais) para conferência ou para alimentar o fluxo de contas a pagar.
    """
    try:
        nfe = NFeImportService.parse(payload.xml_content)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e
    return {"status": "success", "nfe": nfe}


@router.post("/bank-statement/ofx", status_code=status.HTTP_201_CREATED)
async def import_bank_statement_ofx(
    payload: OfxImportRequest,
    db: AsyncSession = Depends(get_db),
    tenant_and_user: tuple[uuid.UUID, uuid.UUID] = Depends(get_current_tenant_and_user),
) -> dict[str, Any]:
    tenant_id, _ = tenant_and_user
    try:
        transactions = await MigrationService.import_bank_statement_ofx(
            db, tenant_id, payload.ofx_content
        )
        await db.commit()
        return {
            "status": "success",
            "message": (
                f"Successfully parsed and imported {len(transactions)} "
                "bank transactions."
            ),
            "transactions": [
                {
                    "id": tx.id,
                    "fitid": tx.fitid,
                    "transaction_date": tx.transaction_date,
                    "amount": tx.amount,
                    "description": tx.description,
                    "reconciled": tx.reconciled,
                }
                for tx in transactions
            ],
        }
    except ValueError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        ) from e

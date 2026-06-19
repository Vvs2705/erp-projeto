from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from fiscal_engine.determination import Operation, Regime, determine
from fiscal_engine.emission import EmissionRequest, Item, Party
from pydantic import BaseModel, Field

from app.core.security import Principal, require_permission
from app.services.fiscal_emission import (
    EmissionError,
    EmissionNotConfigured,
    FiscalEmissionClient,
)

router = APIRouter(prefix="/api/v1/fiscal", tags=["Fiscal"])

_REGIMES = {r.value: r for r in Regime}
_OPERATIONS = {o.value: o for o in Operation}


class TaxCalculationRequest(BaseModel):
    amount: Decimal = Field(gt=0)
    issue_date: date
    is_service: bool = False
    regime: str = Regime.PRESUMIDO.value


class EmitItem(BaseModel):
    code: str
    description: str
    ncm: str
    cfop: str
    quantity: Decimal = Field(gt=0)
    unit_value: Decimal = Field(gt=0)


class EmitRequest(BaseModel):
    issuer_cnpj: str
    issuer_name: str
    recipient_cnpj: str
    recipient_name: str
    issue_date: date
    nature: str
    operation: str = Operation.SALE_GOODS.value
    regime: str = Regime.PRESUMIDO.value
    items: list[EmitItem] = Field(min_length=1)


@router.post("/calculate")
async def calculate_taxes(
    payload: TaxCalculationRequest,
    _: Principal = Depends(require_permission("fiscal.read")),
) -> dict[str, str]:
    """Determina os tributos pela vigência da data de emissão (não emite nada)."""
    regime = _REGIMES.get(payload.regime)
    if regime is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Regime inválido: {payload.regime}",
        )
    operation = Operation.SALE_SERVICE if payload.is_service else Operation.SALE_GOODS
    result = determine(payload.amount, payload.issue_date, operation, regime)
    return {tax: str(value) for tax, value in result.as_dict().items()}


@router.post("/emit", status_code=status.HTTP_201_CREATED)
async def emit_document(
    payload: EmitRequest,
    _: Principal = Depends(require_permission("fiscal.document.issue")),
) -> dict[str, object]:
    """Emite um DF-e via provedor (determinação local + transmissão delegada)."""
    operation = _OPERATIONS.get(payload.operation)
    regime = _REGIMES.get(payload.regime)
    if operation is None or regime is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Operação ou regime inválido.",
        )

    request = EmissionRequest(
        issuer=Party(cnpj=payload.issuer_cnpj, name=payload.issuer_name),
        recipient=Party(cnpj=payload.recipient_cnpj, name=payload.recipient_name),
        operation=operation,
        issue_date=payload.issue_date,
        nature=payload.nature,
        items=tuple(
            Item(
                code=item.code,
                description=item.description,
                ncm=item.ncm,
                cfop=item.cfop,
                quantity=item.quantity,
                unit_value=item.unit_value,
            )
            for item in payload.items
        ),
    )

    client = FiscalEmissionClient()
    try:
        result = await client.emit(request, regime)
    except EmissionNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except EmissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    return {
        "provider": result.provider,
        "status": result.status,
        "protocol": result.protocol,
        "access_key": result.access_key,
    }

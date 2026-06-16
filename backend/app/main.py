import sys
from pathlib import Path
# Resolve the project root directory to make the integrations folder importable
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

import uuid
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.database import tenant_context
from app.routers.finance import router as finance_router
from app.routers.inventory import router as inventory_router
from app.routers.purchase import router as purchase_router
from app.routers.sales import router as sales_router
from app.routers.fiscal import router as fiscal_router
from integrations.banking.webhook_receiver import router as banking_webhook_router
from app.routers.reporting import router as reporting_router
from app.routers.migration import router as migration_router

app = FastAPI(
    title="ERP-V Core API",
    description="ERP-V Modular Monolith Backend - Core Identity and Financial Context",
    version="0.1.0",
)

@app.middleware("http")
async def tenant_middleware(request: Request, call_next):
    """
    Extracts the X-Tenant-ID from request headers, validates it,
    and binds it to a context-local variable. Any DB sessions instantiated
    within this request thread/context will automatically configure the PG session tenant_id.
    """
    tenant_id_str = request.headers.get("X-Tenant-ID")
    token = None
    
    if tenant_id_str:
        try:
            tenant_uuid = uuid.UUID(tenant_id_str)
            token = tenant_context.set(tenant_uuid)
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={"detail": "Invalid X-Tenant-ID header format. Must be a valid UUID."}
            )

    try:
        response = await call_next(request)
    finally:
        if token is not None:
            tenant_context.reset(token)
            
    return response

# Register routers
app.include_router(finance_router)
app.include_router(inventory_router)
app.include_router(purchase_router)
app.include_router(sales_router)
app.include_router(fiscal_router)
app.include_router(banking_webhook_router)
app.include_router(reporting_router)
app.include_router(migration_router)

@app.get("/health")
async def health_check():
    return {"status": "healthy"}


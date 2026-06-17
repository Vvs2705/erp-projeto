# ruff: noqa: E402
"""ERP-V Core API entrypoint.

The integrations package lives at the repository root, so we extend sys.path
before importing it; imports therefore intentionally follow that bootstrap.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from integrations.banking.webhook_receiver import router as banking_webhook_router
from sqlalchemy import text
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.core.config import settings
from app.core.database import engine, tenant_context
from app.core.security import principal_from_token
from app.core.tokens import TokenError
from app.routers.auth import router as auth_router
from app.routers.finance import router as finance_router
from app.routers.fiscal import router as fiscal_router
from app.routers.inventory import router as inventory_router
from app.routers.migration import router as migration_router
from app.routers.purchase import router as purchase_router
from app.routers.reporting import router as reporting_router
from app.routers.sales import router as sales_router

app = FastAPI(
    title="ERP-V Core API",
    description="ERP-V Modular Monolith Backend",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _is_public(path: str) -> bool:
    # API docs are public outside production only.
    if path == "/openapi.json" or path.startswith(("/docs", "/redoc")):
        return not settings.is_production
    return any(path.startswith(prefix) for prefix in settings.public_path_prefixes)


@app.middleware("http")
async def auth_middleware(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    """Authenticate via Bearer access token and bind the tenant for RLS.

    The tenant is derived from the validated token — never from a client-supplied
    header — and is set as a context variable consumed when DB sessions open.
    """
    if _is_public(request.url.path):
        return await call_next(request)

    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        return JSONResponse(
            status_code=401, content={"detail": "Token de acesso ausente."}
        )
    try:
        principal = principal_from_token(authorization[len("Bearer ") :])
    except TokenError:
        return JSONResponse(
            status_code=401,
            content={"detail": "Token de acesso inválido ou expirado."},
        )

    request.state.principal = principal
    ctx_token = tenant_context.set(principal.tenant_id)
    try:
        return await call_next(request)
    finally:
        tenant_context.reset(ctx_token)


app.include_router(auth_router)
app.include_router(finance_router)
app.include_router(inventory_router)
app.include_router(purchase_router)
app.include_router(sales_router)
app.include_router(fiscal_router)
app.include_router(banking_webhook_router)
app.include_router(reporting_router)
app.include_router(migration_router)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Liveness probe: process is up."""
    return {"status": "healthy"}


@app.get("/readiness")
async def readiness_check() -> JSONResponse:
    """Readiness probe: process can reach the database."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # - probe must report any failure
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "error": str(exc)},
        )
    return JSONResponse(content={"status": "ready"})

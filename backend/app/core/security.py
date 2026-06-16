import uuid
from fastapi import Header, HTTPException, status

async def get_current_tenant_and_user(
    x_tenant_id: str = Header(..., alias="X-Tenant-ID"),
    x_user_id: str | None = Header(None, alias="X-User-ID"),
) -> tuple[uuid.UUID, uuid.UUID]:
    """
    Dependency or helper to retrieve tenant_id and user_id from headers.
    Simulates token validation and multi-tenant isolation retrieval.
    """
    try:
        tenant_uuid = uuid.UUID(x_tenant_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid X-Tenant-ID header format. Must be a valid UUID."
        ) from e
    
    user_uuid: uuid.UUID
    if x_user_id:
        try:
            user_uuid = uuid.UUID(x_user_id)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid X-User-ID header format. Must be a valid UUID."
            ) from e
    else:
        # Fallback dummy user UUID for testing/simulation
        user_uuid = uuid.UUID("00000000-0000-0000-0000-000000000001")
        
    return tenant_uuid, user_uuid

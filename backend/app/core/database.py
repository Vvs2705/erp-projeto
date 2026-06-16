import uuid
import contextvars
from typing import AsyncGenerator, Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

# Context variable to hold tenant ID for the current request context
tenant_context: contextvars.ContextVar[Optional[uuid.UUID]] = contextvars.ContextVar("tenant_context", default=None)

# Create async engine with asyncpg
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
)

# Create async sessionmaker
async_session_maker = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Declarative base class for models
class Base(DeclarativeBase):
    pass

# Helper to set the tenant_id in PG session variables (local to current transaction)
async def set_session_tenant(db: AsyncSession, tenant_id: uuid.UUID | str) -> None:
    await db.execute(
        text("SET LOCAL app.current_tenant_id = :tenant_id"),
        {"tenant_id": str(tenant_id)}
    )

# Helper to get the database session
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        t_id = tenant_context.get()
        if t_id:
            # Execute early in session lifecycle. Because autocommit is False,
            # this will begin a transaction and set the local variable.
            await set_session_tenant(session, t_id)
        try:
            yield session
        finally:
            await session.close()


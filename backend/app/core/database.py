import contextvars
import uuid
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

# Context variable to hold tenant ID for the current request context
tenant_context: contextvars.ContextVar[uuid.UUID | None] = contextvars.ContextVar(
    "tenant_context", default=None
)

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


# Helper to set the tenant_id in PG session variables (local to current transaction).
# Uses set_config(..., is_local=true) so the value is scoped to the transaction and
# is the variable read by Row-Level Security policies. No-op on non-PostgreSQL
# backends (e.g. SQLite used in unit tests).
async def set_session_tenant(db: AsyncSession, tenant_id: uuid.UUID | str) -> None:
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return
    await db.execute(
        text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
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

"""Testes do worker de Transactional Outbox — sem mocks, SQLite em memória.

Cobrem o processamento de pendentes: sucesso (completed + processed_at), falha
com retry (volta a pending), dead-letter após max_attempts, seleção apenas de
pendentes, ordem por created_at e limite de lote.
"""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import CheckConstraint, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from app.core.database import Base
from app.models.tenant import Tenant, TransactionalOutbox
from app.services.outbox_service import (
    LoggingOutboxDispatcher,
    OutboxProcessor,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


@compiles(UUID, "sqlite")
def _compile_uuid_sqlite(type_, compiler, **kw):
    return "CHAR(36)"


@pytest_asyncio.fixture(scope="function")
async def db_session():
    for table in Base.metadata.tables.values():
        for c in [c for c in table.constraints if isinstance(c, CheckConstraint)]:
            table.constraints.remove(c)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def tenant_id(db_session: AsyncSession) -> uuid.UUID:
    tenant = Tenant(
        name="Outbox Tenant",
        slug="outbox-tenant",
        status="active",
        subscription_price=Decimal("0.00"),
        billing_limit=Decimal("10000.00"),
    )
    db_session.add(tenant)
    await db_session.flush()
    return tenant.id


_BASE_TS = datetime(2026, 6, 1, 12, 0, 0)


async def _add_events(
    db: AsyncSession, tenant_id: uuid.UUID, count: int, *, status: str = "pending"
) -> list[uuid.UUID]:
    ids: list[uuid.UUID] = []
    for i in range(count):
        event = TransactionalOutbox(
            tenant_id=tenant_id,
            event_type="invoice.created",
            payload={"seq": i},
            status=status,
            created_at=_BASE_TS + timedelta(seconds=i),
        )
        db.add(event)
        await db.flush()
        ids.append(event.id)
    return ids


class _OkDispatcher:
    def __init__(self) -> None:
        self.seen: list[uuid.UUID] = []

    async def dispatch(self, event: TransactionalOutbox) -> None:
        self.seen.append(event.id)


class _FailDispatcher:
    async def dispatch(self, event: TransactionalOutbox) -> None:
        raise RuntimeError("destino indisponível")


@pytest.mark.asyncio
async def test_process_pending_sucesso(
    db_session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    await _add_events(db_session, tenant_id, 3)
    dispatcher = _OkDispatcher()

    counts = await OutboxProcessor.process_pending(db_session, dispatcher)

    assert counts == {"selected": 3, "completed": 3, "failed": 0}
    rows = (await db_session.execute(select(TransactionalOutbox))).scalars().all()
    assert all(r.status == "completed" for r in rows)
    assert all(r.processed_at is not None for r in rows)
    assert all(r.attempts == 1 for r in rows)


@pytest.mark.asyncio
async def test_dispatch_falha_volta_para_pending(
    db_session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    await _add_events(db_session, tenant_id, 1)

    counts = await OutboxProcessor.process_pending(
        db_session, _FailDispatcher(), max_attempts=5
    )

    assert counts == {"selected": 1, "completed": 0, "failed": 1}
    row = (await db_session.execute(select(TransactionalOutbox))).scalars().one()
    assert row.status == "pending"  # ainda há tentativas
    assert row.attempts == 1
    assert row.error_message == "destino indisponível"
    assert row.processed_at is None


@pytest.mark.asyncio
async def test_dead_letter_apos_max_attempts(
    db_session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    await _add_events(db_session, tenant_id, 1)

    counts = await OutboxProcessor.process_pending(
        db_session, _FailDispatcher(), max_attempts=1
    )

    assert counts["failed"] == 1
    row = (await db_session.execute(select(TransactionalOutbox))).scalars().one()
    assert row.status == "failed"  # dead-letter terminal
    assert row.attempts == 1


@pytest.mark.asyncio
async def test_so_processa_pending(
    db_session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    done = await _add_events(db_session, tenant_id, 1, status="completed")
    await _add_events(db_session, tenant_id, 1, status="pending")
    dispatcher = _OkDispatcher()

    counts = await OutboxProcessor.process_pending(db_session, dispatcher)

    assert counts["selected"] == 1
    # O evento já 'completed' não foi reprocessado.
    assert done[0] not in dispatcher.seen


@pytest.mark.asyncio
async def test_ordem_e_limite(db_session: AsyncSession, tenant_id: uuid.UUID) -> None:
    ids = await _add_events(db_session, tenant_id, 5)
    dispatcher = _OkDispatcher()

    counts = await OutboxProcessor.process_pending(db_session, dispatcher, limit=2)

    assert counts["selected"] == 2
    # Processa os 2 mais antigos, em ordem de created_at.
    assert dispatcher.seen == ids[:2]


@pytest.mark.asyncio
async def test_logging_dispatcher_smoke(
    db_session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    [event_id] = await _add_events(db_session, tenant_id, 1)
    event = (
        (
            await db_session.execute(
                select(TransactionalOutbox).where(TransactionalOutbox.id == event_id)
            )
        )
        .scalars()
        .one()
    )
    # Não deve levantar.
    await LoggingOutboxDispatcher().dispatch(event)

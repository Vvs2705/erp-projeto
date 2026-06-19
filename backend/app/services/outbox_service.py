"""Worker do Transactional Outbox: entrega confiável de eventos de domínio.

Eventos são gravados em ``transactional_outbox`` na MESMA transação da mudança
de estado de negócio (garantia atômica). Este processador lê os pendentes e os
entrega via um ``OutboxDispatcher`` plugável, com controle de tentativas e
dead-letter — sem perder nem duplicar silenciosamente.

O destino real (broker/webhook) implementa ``OutboxDispatcher`` e é injetado; o
padrão ``LoggingOutboxDispatcher`` apenas registra (não há destino externo
configurado), no mesmo espírito da observabilidade no-op sem env. Em produção o
worker roda com conexão privilegiada (BYPASSRLS) para enxergar todos os tenants.
"""

from datetime import datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.observability import get_logger
from app.models.tenant import TransactionalOutbox

logger = get_logger(__name__)

DEFAULT_MAX_ATTEMPTS = 5


class OutboxDispatcher(Protocol):
    """Entrega um evento ao destino. Deve levantar exceção em caso de falha."""

    async def dispatch(self, event: TransactionalOutbox) -> None: ...


class LoggingOutboxDispatcher:
    """Dispatcher padrão: registra o evento (sem destino externo configurado)."""

    async def dispatch(self, event: TransactionalOutbox) -> None:
        logger.info(
            "outbox.dispatch",
            event_id=str(event.id),
            event_type=event.event_type,
            tenant_id=str(event.tenant_id),
        )


class OutboxProcessor:
    @staticmethod
    async def process_pending(
        db: AsyncSession,
        dispatcher: OutboxDispatcher,
        *,
        limit: int = 100,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> dict[str, int]:
        """Processa um lote de eventos pendentes em ordem de criação.

        Cada evento vira ``processing`` antes do envio. Em sucesso → ``completed``
        (com ``processed_at``). Em falha → incrementa ``attempts`` e registra o
        erro; volta a ``pending`` para nova tentativa até ``max_attempts``, quando
        então fica ``failed`` (dead-letter). Devolve a contagem do lote.
        """
        stmt = (
            select(TransactionalOutbox)
            .where(TransactionalOutbox.status == "pending")
            .order_by(TransactionalOutbox.created_at)
            .limit(limit)
        )
        result = await db.execute(stmt)
        events = list(result.scalars().all())

        completed = 0
        failed = 0
        for event in events:
            event.status = "processing"
            await db.flush()
            try:
                await dispatcher.dispatch(event)
            except Exception as exc:
                event.attempts += 1
                event.error_message = str(exc)
                event.status = "failed" if event.attempts >= max_attempts else "pending"
                failed += 1
                logger.warning(
                    "outbox.dispatch_failed",
                    event_id=str(event.id),
                    event_type=event.event_type,
                    attempts=event.attempts,
                    status=event.status,
                    error=str(exc),
                )
            else:
                event.attempts += 1
                event.status = "completed"
                event.processed_at = datetime.utcnow()
                event.error_message = None
                completed += 1
            await db.flush()

        return {"selected": len(events), "completed": completed, "failed": failed}

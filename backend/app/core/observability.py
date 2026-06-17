"""Observabilidade: OpenTelemetry, Sentry SDK e logging estruturado em JSON.

Chamada obrigatória: ``init_observability(app)`` no startup do FastAPI.
Toda configuração é feita por variáveis de ambiente; sem as variáveis as
features são no-ops (nenhum overhead em testes).
"""

from __future__ import annotations

import logging
import sys
import uuid
from typing import Any

import structlog

from app.core.config import settings


def _configure_structlog() -> None:
    """Configura structlog para emitir JSON lines no stdout."""
    timestamper = structlog.processors.TimeStamper(fmt="iso")
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[*shared_processors, structlog.processors.JSONRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Redireciona o logging stdlib para structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )


def _init_sentry() -> None:
    """Inicializa Sentry; no-op se SENTRY_DSN não estiver configurado."""
    if not settings.SENTRY_DSN:
        return

    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENV,
        integrations=[FastApiIntegration(), SqlalchemyIntegration()],
        traces_sample_rate=0.05,
        send_default_pii=False,
    )


def _init_otel(app: Any) -> None:
    """Registra tracer OTel e instrumenta FastAPI + SQLAlchemy.

    No-op se OTEL_ENABLED=false.
    """
    if not settings.OTEL_ENABLED:
        return

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create(
        {
            "service.name": settings.SERVICE_NAME,
            "deployment.environment": settings.ENV,
        }
    )
    provider = TracerProvider(resource=resource)

    endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT
    if endpoint:
        exporter = OTLPSpanExporter(endpoint=endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
    SQLAlchemyInstrumentor().instrument()


def init_observability(app: Any = None) -> None:
    """Inicializa toda a stack de observabilidade. Chamar uma vez no startup."""
    _configure_structlog()
    _init_sentry()
    if app is not None:
        _init_otel(app)


def get_logger(name: str) -> Any:
    """Retorna um structlog logger associado ao nome do módulo."""
    return structlog.get_logger(name)


def new_request_id() -> str:
    """Gera um UUID único para correlacionar logs de uma request."""
    return str(uuid.uuid4())

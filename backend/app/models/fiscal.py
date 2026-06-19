import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FiscalDocumentTax(Base):
    """Tributo determinado para um documento fiscal, persistido para apuração.

    Cada linha é um tributo (CBS, IBS, ICMS, ...) incidente sobre um documento.
    O campo ``direction`` define o papel na apuração não-cumulativa:

    - ``debit``  — saída (venda): imposto devido pelo contribuinte.
    - ``credit`` — entrada (compra): imposto creditável.

    A apuração de um período é ``débitos - créditos`` por tributo. ``document_id``
    é uma referência polimórfica (invoice/bill/NF-e) — sem FK rígida, pois o
    documento de origem varia. A tabela tem RLS por tenant.
    """

    __tablename__ = "fiscal_document_taxes"
    __table_args__ = (
        CheckConstraint(
            "direction IN ('debit', 'credit')",
            name="chk_fiscal_document_taxes_direction",
        ),
        CheckConstraint("base >= 0", name="chk_fiscal_document_taxes_base"),
        CheckConstraint("rate >= 0", name="chk_fiscal_document_taxes_rate"),
        CheckConstraint("amount >= 0", name="chk_fiscal_document_taxes_amount"),
        Index(
            "ix_fiscal_document_taxes_apuracao",
            "tenant_id",
            "issue_date",
            "tax",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    # Tipo do documento de origem (ex.: 'sale', 'purchase', 'nfe') — rastreio.
    document_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # Referência polimórfica ao documento de origem (sem FK rígida).
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    document_number: Mapped[str] = mapped_column(String(50), nullable=False)
    # Papel na apuração: 'debit' (saída/devido) | 'credit' (entrada/creditável).
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    # Sigla do tributo: 'cbs', 'ibs', 'icms', 'ipi', 'pis', 'cofins', 'iss'.
    tax: Mapped[str] = mapped_column(String(20), nullable=False)
    base: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

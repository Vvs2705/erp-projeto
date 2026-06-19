"""fiscal_document_taxes (apuração RTC — CBS/IBS)

Revision ID: d4b8e1c3f607
Revises: c7f3a1b29d84
Create Date: 2026-06-19 13:00:00.000000

Cria a tabela ``fiscal_document_taxes``, que persiste cada tributo determinado
para um documento fiscal (CBS, IBS, ICMS, ...), marcado como ``debit``
(saída/devido) ou ``credit`` (entrada/creditável). É a base para a apuração
não-cumulativa por período (``débitos - créditos``) feita por
``FiscalApuracaoService``.

A tabela é tenant-scoped: aplica o mesmo padrão de RLS por tenant das demais
tabelas (revisão a5cc2723e0b0) — ENABLE + FORCE + policy ``tenant_isolation``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4b8e1c3f607"
down_revision: str | None = "c7f3a1b29d84"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "fiscal_document_taxes"
_PREDICATE = (
    "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
)


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("document_type", sa.String(length=30), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("document_number", sa.String(length=50), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("tax", sa.String(length=20), nullable=False),
        sa.Column("base", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("rate", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "direction IN ('debit', 'credit')",
            name="chk_fiscal_document_taxes_direction",
        ),
        sa.CheckConstraint("base >= 0", name="chk_fiscal_document_taxes_base"),
        sa.CheckConstraint("rate >= 0", name="chk_fiscal_document_taxes_rate"),
        sa.CheckConstraint("amount >= 0", name="chk_fiscal_document_taxes_amount"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_fiscal_document_taxes_apuracao",
        _TABLE,
        ["tenant_id", "issue_date", "tax"],
    )

    # RLS por tenant (mesmo padrão de a5cc2723e0b0).
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {_TABLE} "
        f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {_TABLE}")
    op.execute(f"ALTER TABLE {_TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_fiscal_document_taxes_apuracao", table_name=_TABLE)
    op.drop_table(_TABLE)

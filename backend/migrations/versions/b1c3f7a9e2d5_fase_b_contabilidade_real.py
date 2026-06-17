"""fase_b_contabilidade_real

Revision ID: b1c3f7a9e2d5
Revises: a5cc2723e0b0
Create Date: 2026-06-17 00:00:00.000000

Fase B — Contabilidade de verdade:
  1. Adiciona colunas ``nature`` e ``allow_posting`` à tabela ``accounts``.
  2. Cria tabela ``period_closings`` para registrar fechamentos de período.
  3. Adiciona trigger de imutabilidade: impede UPDATE/DELETE em lançamentos e
     linhas de lançamentos com status 'posted'.
  4. Adiciona RLS + policy à nova tabela ``period_closings``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1c3f7a9e2d5"
down_revision: str | None = "a5cc2723e0b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PREDICATE = (
    "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
)

# ── Função e triggers de imutabilidade ────────────────────────────────────────

_CREATE_IMMUTABLE_ENTRY_FUNC = """
CREATE OR REPLACE FUNCTION prevent_posted_entry_modification()
RETURNS trigger AS $$
BEGIN
  IF OLD.status = 'posted' THEN
    RAISE EXCEPTION
      'Lançamento postado é imutável. Use estorno (storno) para reverter. id=%', OLD.id
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN OLD;
END;
$$ LANGUAGE plpgsql;
"""

_CREATE_IMMUTABLE_LINE_FUNC = """
CREATE OR REPLACE FUNCTION prevent_posted_line_modification()
RETURNS trigger AS $$
DECLARE
  entry_status text;
BEGIN
  SELECT status INTO entry_status
    FROM journal_entries
   WHERE id = COALESCE(OLD.journal_entry_id, NEW.journal_entry_id);

  IF entry_status = 'posted' THEN
    RAISE EXCEPTION
      'Linhas de lançamento postado são imutáveis. id=%', COALESCE(OLD.id, NEW.id)
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN OLD;
END;
$$ LANGUAGE plpgsql;
"""

_CREATE_ENTRY_TRIGGER = """
CREATE TRIGGER immutable_journal_entries
BEFORE UPDATE OR DELETE ON journal_entries
FOR EACH ROW EXECUTE FUNCTION prevent_posted_entry_modification();
"""

_CREATE_LINE_TRIGGER = """
CREATE TRIGGER immutable_journal_lines
BEFORE UPDATE OR DELETE ON journal_lines
FOR EACH ROW EXECUTE FUNCTION prevent_posted_line_modification();
"""


def upgrade() -> None:
    # 1. Adiciona nature e allow_posting à tabela accounts
    op.add_column(
        "accounts",
        sa.Column(
            "nature",
            sa.String(6),
            nullable=False,
            server_default="debit",
        ),
    )
    op.add_column(
        "accounts",
        sa.Column(
            "allow_posting",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.create_check_constraint(
        "chk_accounts_nature",
        "accounts",
        "nature IN ('debit', 'credit')",
    )

    # Deriva nature automaticamente a partir do tipo existente
    op.execute(
        """
        UPDATE accounts
           SET nature = CASE
                          WHEN type IN ('asset', 'expense') THEN 'debit'
                          ELSE 'credit'
                        END
        """
    )

    # 2. Cria tabela period_closings
    op.create_table(
        "period_closings",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "fiscal_period_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fiscal_periods.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "closing_entry_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("journal_entries.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("net_result", sa.Numeric(18, 4), nullable=False),
        sa.Column(
            "closed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("closed_by", sa.String(255), nullable=False),
    )

    # 3. RLS na nova tabela
    op.execute("ALTER TABLE period_closings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE period_closings FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON period_closings "
        f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
    )

    # 4. Triggers de imutabilidade
    op.execute(_CREATE_IMMUTABLE_ENTRY_FUNC)
    op.execute(_CREATE_IMMUTABLE_LINE_FUNC)
    op.execute(_CREATE_ENTRY_TRIGGER)
    op.execute(_CREATE_LINE_TRIGGER)


def downgrade() -> None:
    # Remove triggers e funções
    op.execute("DROP TRIGGER IF EXISTS immutable_journal_lines ON journal_lines")
    op.execute("DROP TRIGGER IF EXISTS immutable_journal_entries ON journal_entries")
    op.execute("DROP FUNCTION IF EXISTS prevent_posted_line_modification()")
    op.execute("DROP FUNCTION IF EXISTS prevent_posted_entry_modification()")

    # Remove RLS e tabela period_closings
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON period_closings")
    op.execute("ALTER TABLE period_closings NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE period_closings DISABLE ROW LEVEL SECURITY")
    op.drop_table("period_closings")

    # Remove colunas de accounts
    op.drop_constraint("chk_accounts_nature", "accounts", type_="check")
    op.drop_column("accounts", "allow_posting")
    op.drop_column("accounts", "nature")

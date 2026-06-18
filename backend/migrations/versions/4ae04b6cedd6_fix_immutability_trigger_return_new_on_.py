"""fix immutability trigger return new on update

Revision ID: 4ae04b6cedd6
Revises: b1c3f7a9e2d5
Create Date: 2026-06-18 16:44:48.237946

Corrige um bug no trigger de imutabilidade introduzido em b1c3f7a9e2d5: as
funções retornavam OLD em BEFORE UPDATE, o que **revertia silenciosamente**
qualquer UPDATE legítimo (inclusive postar um rascunho: draft -> posted).

A regra correta é: bloquear (RAISE) apenas quando o lançamento já está
'posted'; caso contrário, permitir a operação — RETURN NEW para UPDATE e
RETURN OLD para DELETE.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4ae04b6cedd6"
down_revision: str | None = "b1c3f7a9e2d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_FIXED_ENTRY_FUNC = """
CREATE OR REPLACE FUNCTION prevent_posted_entry_modification()
RETURNS trigger AS $$
BEGIN
  IF OLD.status = 'posted' THEN
    RAISE EXCEPTION
      'Lançamento postado é imutável. Use estorno (storno) para reverter. id=%', OLD.id
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

_FIXED_LINE_FUNC = """
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
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

# Versões originais (com o bug RETURN OLD) — usadas no downgrade.
_BUGGY_ENTRY_FUNC = """
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

_BUGGY_LINE_FUNC = """
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


def upgrade() -> None:
    op.execute(_FIXED_ENTRY_FUNC)
    op.execute(_FIXED_LINE_FUNC)


def downgrade() -> None:
    op.execute(_BUGGY_ENTRY_FUNC)
    op.execute(_BUGGY_LINE_FUNC)

"""bank reconciliation match link (conciliação bancária)

Revision ID: f5a1d2c9b730
Revises: e3f9a2c8b614
Create Date: 2026-06-20 15:30:00.000000

Adiciona à ``bank_transactions`` o vínculo 1:1 da conciliação: a linha do extrato
passa a referenciar o pagamento contabilizado que a liquidou.

- ``matched_kind``: ``invoice_payment`` (entrada → recebimento de cliente) ou
  ``bill_payment`` (saída → pagamento a fornecedor); NULL enquanto não conciliada.
- ``matched_payment_id``: id do pagamento na tabela indicada por ``matched_kind``.

A tabela já é tenant-scoped e está sob RLS (revisão a5cc2723e0b0); apenas colunas
são adicionadas — a policy existente continua valendo.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f5a1d2c9b730"
down_revision: str | None = "e3f9a2c8b614"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "bank_transactions",
        sa.Column("matched_kind", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "bank_transactions",
        sa.Column("matched_payment_id", sa.UUID(), nullable=True),
    )
    op.create_check_constraint(
        "chk_bank_transactions_matched_kind",
        "bank_transactions",
        "matched_kind IS NULL OR "
        "matched_kind IN ('invoice_payment', 'bill_payment')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "chk_bank_transactions_matched_kind",
        "bank_transactions",
        type_="check",
    )
    op.drop_column("bank_transactions", "matched_payment_id")
    op.drop_column("bank_transactions", "matched_kind")

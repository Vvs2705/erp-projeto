"""add organization_id to stock_moves

Revision ID: c7f3a1b29d84
Revises: 4ae04b6cedd6
Create Date: 2026-06-19 12:10:00.000000

Vincula cada movimento de estoque à organização (unidade de negócio) dentro do
tenant. O parâmetro ``organization_id`` já era recebido por
``InventoryService.register_stock_move`` mas não era persistido; agora é gravado
na coluna correspondente. A tabela ``stock_moves`` já possui RLS por tenant
(revisão a5cc2723e0b0); a coluna é NOT NULL com FK para ``organizations``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7f3a1b29d84"
down_revision: str | None = "4ae04b6cedd6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stock_moves",
        sa.Column("organization_id", sa.UUID(), nullable=False),
    )
    op.create_foreign_key(
        "fk_stock_moves_organization_id",
        "stock_moves",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_stock_moves_organization_id", "stock_moves", type_="foreignkey"
    )
    op.drop_column("stock_moves", "organization_id")

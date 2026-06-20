"""inventory lot/serial tracking (valoração lote/série)

Revision ID: e3f9a2c8b614
Revises: d4b8e1c3f607
Create Date: 2026-06-20 14:00:00.000000

Adiciona rastreamento de estoque por **lote** e por **série**:

- ``products.tracking_mode`` (``none`` | ``lot`` | ``serial``) define o método de
  custo de saída — MPM (padrão), PEPS/FIFO por lote, ou identificação específica
  por série.
- ``stock_lots``: camadas de custo por lote (saldo + custo unitário + validade).
- ``stock_serials``: unidades serializadas (custo próprio + status in_stock/consumed).

Ambas as novas tabelas são tenant-scoped e recebem o mesmo padrão de RLS por
tenant (revisão a5cc2723e0b0): ENABLE + FORCE + policy ``tenant_isolation``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e3f9a2c8b614"
down_revision: str | None = "d4b8e1c3f607"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PREDICATE = (
    "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
)
_NEW_TABLES = ("stock_lots", "stock_serials")


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
    )


def _disable_rls(table: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


def upgrade() -> None:
    # 1) products.tracking_mode
    op.add_column(
        "products",
        sa.Column(
            "tracking_mode",
            sa.String(length=10),
            nullable=False,
            server_default="none",
        ),
    )
    op.create_check_constraint(
        "chk_products_tracking_mode",
        "products",
        "tracking_mode IN ('none', 'lot', 'serial')",
    )

    # 2) stock_lots
    op.create_table(
        "stock_lots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("lot_number", sa.String(length=100), nullable=False),
        sa.Column("qty_on_hand", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("unit_cost", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("qty_on_hand >= 0", name="chk_stock_lots_qty_on_hand"),
        sa.CheckConstraint("unit_cost >= 0", name="chk_stock_lots_unit_cost"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "product_id", "lot_number", name="uq_stock_lots_product_lot"
        ),
    )
    # Índice para a varredura PEPS/FIFO (validade, depois entrada).
    op.create_index(
        "ix_stock_lots_fifo",
        "stock_lots",
        ["tenant_id", "product_id", "expiry_date", "created_at"],
    )

    # 3) stock_serials
    op.create_table(
        "stock_serials",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("serial_number", sa.String(length=100), nullable=False),
        sa.Column("unit_cost", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="in_stock",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('in_stock', 'consumed')", name="chk_stock_serials_status"
        ),
        sa.CheckConstraint("unit_cost >= 0", name="chk_stock_serials_unit_cost"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "product_id",
            "serial_number",
            name="uq_stock_serials_product_serial",
        ),
    )
    op.create_index(
        "ix_stock_serials_lookup",
        "stock_serials",
        ["tenant_id", "product_id", "status"],
    )

    for table in _NEW_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    for table in _NEW_TABLES:
        _disable_rls(table)
    op.drop_index("ix_stock_serials_lookup", table_name="stock_serials")
    op.drop_table("stock_serials")
    op.drop_index("ix_stock_lots_fifo", table_name="stock_lots")
    op.drop_table("stock_lots")
    op.drop_constraint("chk_products_tracking_mode", "products", type_="check")
    op.drop_column("products", "tracking_mode")

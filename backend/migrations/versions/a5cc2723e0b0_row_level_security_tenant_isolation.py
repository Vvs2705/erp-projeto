"""row level security tenant isolation

Revision ID: a5cc2723e0b0
Revises: a0ff922b205d
Create Date: 2026-06-16 22:46:00.798258

Enables and FORCES Row-Level Security on every tenant-scoped table, with a
policy that only exposes rows whose ``tenant_id`` matches the transaction-local
GUC ``app.current_tenant_id`` (set by app.core.database.set_session_tenant).

If the GUC is unset the predicate evaluates to NULL -> no rows (deny by
default). NOTE: PostgreSQL superusers bypass RLS even with FORCE; the
application must connect as a NON-superuser role in every environment for this
isolation to take effect.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a5cc2723e0b0"
down_revision: str | None = "a0ff922b205d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Tables carrying a tenant_id column that must be isolated per tenant.
TENANT_TABLES: tuple[str, ...] = (
    "accounts",
    "audit_logs",
    "bank_transactions",
    "bill_payments",
    "bills",
    "fiscal_periods",
    "invoice_payments",
    "invoices",
    "journal_entries",
    "journal_lines",
    "journals",
    "legal_entities",
    "organizations",
    "partners",
    "products",
    "purchase_order_items",
    "purchase_orders",
    "purchase_requisitions",
    "refresh_tokens",
    "roles",
    "sales_order_items",
    "sales_orders",
    "sales_quotations",
    "stock_moves",
    "stock_valuations",
    "transactional_outbox",
    "user_roles",
    "user_tenants",
)

_PREDICATE = (
    "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
)


def upgrade() -> None:
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
        )


def downgrade() -> None:
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

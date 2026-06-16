import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Numeric, DateTime, ForeignKey, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

class PurchaseRequisition(Base):
    __tablename__ = "purchase_requisitions"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'pending_approval', 'approved', 'rejected')", name="chk_purchase_requisitions_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="draft", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'approved', 'received')", name="chk_purchase_orders_status"),
        CheckConstraint("cnpj ~ '^[A-Z0-9]{14}$'", name="chk_purchase_orders_cnpj_format"),
        CheckConstraint("total_amount >= 0", name="chk_purchase_orders_total_amount"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(255), nullable=False)
    cnpj: Mapped[str] = mapped_column(String(14), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="draft", nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0.0000"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    items: Mapped[list["PurchaseOrderItem"]] = relationship(back_populates="purchase_order", cascade="all, delete-orphan")


class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="chk_purchase_order_items_quantity"),
        CheckConstraint("unit_cost >= 0", name="chk_purchase_order_items_unit_cost"),
        CheckConstraint("quantity_received >= 0", name="chk_purchase_order_items_quantity_received"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    quantity_received: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0.0000"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    # Relationships
    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="items")
